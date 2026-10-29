"""A paid checkout is applied even when the browser never reports back.

A one-time checkout was activated only by the browser calling
``/verify-payment`` after Razorpay's checkout succeeded. If that call never
landed — the tab closed, the connection dropped, the API restarted mid-request
during a deploy — the customer had paid, was not upgraded, and nothing on the
server would ever notice. Razorpay's ``order.paid`` webhook is the server-to-
server answer; it now runs the same activation the browser path does.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from app.models.subscription import SubscriptionStatus, SubscriptionTier
from app.models.subscription_payment import SubscriptionPayment
from app.services import razorpay_client
from app.services import usage as usage_service
from tests.test_subscriptions import _paid_order

HOOK = "/api/v1/subscriptions/webhook"
VERIFY = "/api/v1/subscriptions/verify-payment"


def _order_paid(business_id, tier="pro", order_id="order_test", payment_id="pay_hook"):
    return {
        "entity": "event",
        "event": "order.paid",
        "contains": ["payment", "order"],
        "payload": {
            "payment": {"entity": {"id": payment_id, "order_id": order_id, "status": "captured"}},
            "order": {"entity": {
                "id": order_id, "status": "paid",
                "receipt": razorpay_client.order_receipt(business_id, SubscriptionTier(tier)),
            }},
        },
    }


def _hook(client, payload, *, order=None):
    with patch.object(razorpay_client, "verify_webhook_signature", return_value=True), \
         patch.object(razorpay_client, "fetch_order", return_value=order):
        return client.post(HOOK, content=json.dumps(payload).encode(),
                           headers={"X-Razorpay-Signature": "sig"})


def _payments(db, business_id):
    return db.query(SubscriptionPayment).filter_by(business_id=business_id).count()


def test_the_webhook_activates_a_checkout_the_browser_never_confirmed(
    client, db_session, business
):
    response = _hook(client, _order_paid(business.id), order=_paid_order(business.id, "pro"))

    assert response.status_code == 200, response.text
    sub = usage_service.get_subscription(db_session, business.id)
    assert sub is not None and sub.tier is SubscriptionTier.PRO
    assert sub.status is SubscriptionStatus.ACTIVE
    assert _payments(db_session, business.id) == 1


def test_the_browser_confirming_afterwards_applies_nothing_twice(
    auth_client, db_session, business
):
    _hook(auth_client, _order_paid(business.id), order=_paid_order(business.id, "pro"))
    end = usage_service.get_subscription(db_session, business.id).current_period_end

    with patch.object(razorpay_client, "verify_payment_signature", return_value=True), \
         patch.object(razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")):
        response = auth_client.post(VERIFY, json={
            "razorpay_order_id": "order_test", "razorpay_payment_id": "pay_hook",
            "razorpay_signature": "sig", "tier": "pro"})

    assert response.status_code == 200
    db_session.expire_all()
    assert _payments(db_session, business.id) == 1
    assert usage_service.get_subscription(db_session, business.id).current_period_end == end


def test_the_webhook_after_the_browser_applies_nothing_twice(auth_client, db_session, business):
    with patch.object(razorpay_client, "verify_payment_signature", return_value=True), \
         patch.object(razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")):
        auth_client.post(VERIFY, json={
            "razorpay_order_id": "order_test", "razorpay_payment_id": "pay_hook",
            "razorpay_signature": "sig", "tier": "pro"})

    assert _hook(auth_client, _order_paid(business.id),
                 order=_paid_order(business.id, "pro")).status_code == 200
    assert _payments(db_session, business.id) == 1


def test_razorpay_unreachable_is_a_502_so_razorpay_retries(client, db_session, business):
    response = _hook(client, _order_paid(business.id), order=None)
    assert response.status_code == 502
    assert usage_service.get_subscription(db_session, business.id) is None


def test_an_order_that_does_not_match_is_acknowledged_and_not_applied(
    client, db_session, business
):
    wrong = _paid_order(business.id, "pro") | {"amount": 1, "amount_paid": 1}
    response = _hook(client, _order_paid(business.id), order=wrong)
    assert response.status_code == 200  # retrying cannot change the answer
    assert usage_service.get_subscription(db_session, business.id) is None


def test_a_receipt_naming_no_business_is_acknowledged(client):
    assert _hook(client, _order_paid(999999), order=None).status_code == 200
