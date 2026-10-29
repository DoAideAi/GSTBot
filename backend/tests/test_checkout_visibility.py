"""Checkout verification is counted, not only logged.

P29 counted Razorpay webhook outcomes; checkout completes through
``POST /subscriptions/verify-payment`` and ``POST /reconciliation/report/verify``,
which had no counters at all. A rotated key secret refuses every real payment's
signature, an unreachable Razorpay 502s every one — customers charged and not
upgraded — and the only trace was a log line per payment.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core import metrics
from app.services import razorpay_client
from tests.test_subscriptions import _paid_order

URL = "/api/v1/subscriptions/verify-payment"
BODY = {
    "razorpay_order_id": "order_test",
    "razorpay_payment_id": "pay_test",
    "razorpay_signature": "sig",
    "tier": "pro",
}


@pytest.fixture()
def counted(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = metrics.count

    def count(event, n=1, **kwargs):
        seen.append(event)
        real(event, n, **kwargs)  # still validates the name against EVENTS

    monkeypatch.setattr(metrics, "count", count)
    return seen


def test_an_applied_payment_is_counted(auth_client, business, counted):
    with patch.object(razorpay_client, "verify_payment_signature", return_value=True), \
         patch.object(razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")):
        assert auth_client.post(URL, json=BODY).status_code == 200
    assert counted == ["checkout_payment_applied"]


def test_a_refused_signature_is_counted(auth_client, counted):
    with patch.object(razorpay_client, "verify_payment_signature", return_value=False):
        assert auth_client.post(URL, json=BODY).status_code == 400
    assert counted == ["checkout_payment_refused"]


def test_razorpay_unreachable_is_counted(auth_client, counted):
    with patch.object(razorpay_client, "verify_payment_signature", return_value=True), \
         patch.object(razorpay_client, "fetch_order", return_value=None):
        assert auth_client.post(URL, json=BODY).status_code == 502
    assert counted == ["checkout_provider_unreachable"]


def test_a_report_payment_is_counted_under_its_own_name(auth_client, counted):
    with patch.object(razorpay_client, "verify_payment_signature", return_value=False):
        response = auth_client.post(
            "/api/v1/reconciliation/report/verify",
            json={"run_id": 1, "razorpay_order_id": "order_x",
                  "razorpay_payment_id": "pay_x", "razorpay_signature": "sig"},
        )
    # No such run here, so it is refused before the signature is read: a 404,
    # and still a refusal by the count.
    assert response.status_code in (400, 404), response.text
    assert counted == ["report_payment_refused"]


def test_every_outcome_reaches_the_metrics_summary():
    for flow in ("checkout", "report"):
        for outcome in ("applied", "refused", "conflict", "provider_unreachable", "failed"):
            name = f"{flow}_payment_{outcome}" if outcome != "provider_unreachable" \
                else f"{flow}_provider_unreachable"
            assert name in metrics.EVENTS, name
