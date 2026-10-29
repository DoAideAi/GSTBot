"""A payment refunded in full takes back the plan it bought.

Every plan here is a one-time Razorpay order, stored under the id of the
payment that bought it. When that payment is refunded from the Razorpay
dashboard — a duplicate charge the checkout itself flags as "refund due",
a goodwill refund — Razorpay sends ``refund.processed``. The webhook matched
the subscription by that payment id, found no transition for the event and
acknowledged it "without a status change": the business had its money back
and kept the paid plan until the period ran out.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.services import razorpay_client

URL = "/api/v1/subscriptions/webhook"


def _paid(db_session, business, payment_id="pay_bought"):
    sub = Subscription(
        business_id=business.id,
        tier=SubscriptionTier.PRO,
        status=SubscriptionStatus.ACTIVE,
        razorpay_subscription_id=payment_id,
        current_period_end=datetime.now(UTC) + timedelta(days=20),
    )
    db_session.add(sub)
    db_session.commit()
    return sub


def _refund(client, payment_id, *, amount=49900, refunded=49900, event="refund.processed"):
    payload = {
        "event": event,
        "payload": {
            "refund": {"entity": {"id": "rfnd_1", "payment_id": payment_id, "amount": refunded}},
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount,
                    "amount_refunded": refunded,
                    "refund_status": "full" if refunded >= amount else "partial",
                }
            },
        },
    }
    with patch.object(razorpay_client, "verify_webhook_signature", return_value=True):
        return client.post(
            URL, content=json.dumps(payload).encode(), headers={"X-Razorpay-Signature": "v"}
        )


def test_a_full_refund_ends_the_plan_it_paid_for(client, db_session, business):
    sub = _paid(db_session, business)

    response = _refund(client, "pay_bought")

    assert response.status_code == 200
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.CANCELLED
    assert not sub.is_paid()


def test_a_partial_refund_leaves_the_plan_alone(client, db_session, business):
    sub = _paid(db_session, business)

    _refund(client, "pay_bought", refunded=10000)

    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.ACTIVE


def test_refunding_some_other_payment_changes_nothing(client, db_session, business):
    # The duplicate of a charge, refunded as the checkout asked: the plan
    # rests on the first payment, which nobody refunded.
    sub = _paid(db_session, business)

    _refund(client, "pay_the_duplicate")

    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.ACTIVE


def test_a_refund_only_requested_is_not_yet_money_returned(client, db_session, business):
    sub = _paid(db_session, business)

    _refund(client, "pay_bought", event="refund.created")

    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.ACTIVE
