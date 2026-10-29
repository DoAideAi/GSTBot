"""Billing webhooks are counted, not only logged.

A drifted ``RAZORPAY_WEBHOOK_SECRET`` refuses every real payment event with a
401 — one WARNING line per event in a busy log, nothing on the metrics view,
until Razorpay disables the webhook for failing. An event that verifies but
names no subscription was acknowledged and dropped the same way. Each outcome
now has a business-event counter on ``/health/metrics``.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.core import metrics
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.services import razorpay_client

URL = "/api/v1/subscriptions/webhook"


@pytest.fixture()
def counted(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = metrics.count

    def count(event, n=1, **kwargs):
        seen.append(event)
        real(event, n, **kwargs)  # still validates the name against EVENTS

    monkeypatch.setattr(metrics, "count", count)
    return seen


def _post(client, payload, *, verified=True, raw=None):
    with patch.object(razorpay_client, "verify_webhook_signature", return_value=verified):
        return client.post(
            URL,
            content=raw if raw is not None else json.dumps(payload).encode(),
            headers={"X-Razorpay-Signature": "sig"},
        )


def _sub(db, business, razorpay_id, status):
    db.add(Subscription(business_id=business.id, tier=SubscriptionTier.PRO,
                        status=status, razorpay_subscription_id=razorpay_id))
    db.commit()


def test_a_refused_signature_is_counted(client, counted):
    assert _post(client, {}, verified=False).status_code == 401
    assert counted == ["razorpay_webhook_refused"]


def test_a_body_that_is_not_json_is_counted(client, counted):
    assert _post(client, None, raw=b"{nope").status_code == 400
    assert counted == ["razorpay_webhook_malformed"]


def test_an_event_for_no_known_subscription_is_counted(client, counted):
    _post(client, {"event": "payment.failed",
                   "payload": {"payment": {"entity": {"id": "pay_nobody"}}}})
    assert counted == ["razorpay_webhook_unmatched"]


def test_an_applied_transition_is_counted(client, db_session, business, counted):
    _sub(db_session, business, "sub_vis1", SubscriptionStatus.ACTIVE)
    _post(client, {"event": "subscription.halted",
                   "payload": {"subscription": {"entity": {"id": "sub_vis1"}}}})
    assert counted == ["razorpay_webhook_applied"]


def test_an_event_that_changes_nothing_is_counted(client, db_session, business, counted):
    _sub(db_session, business, "sub_vis2", SubscriptionStatus.ACTIVE)
    _post(client, {"event": "subscription.charged",
                   "payload": {"subscription": {"entity": {"id": "sub_vis2"}}}})
    assert counted == ["razorpay_webhook_ignored"]


def test_the_counters_reach_the_metrics_summary():
    for name in ("razorpay_webhook_refused", "razorpay_webhook_malformed",
                 "razorpay_webhook_unmatched", "razorpay_webhook_applied",
                 "razorpay_webhook_ignored"):
        assert name in metrics.EVENTS
