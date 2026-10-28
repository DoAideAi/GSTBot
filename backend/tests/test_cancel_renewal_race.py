"""A cancel that crosses a renewal.

Cancel reads the subscription, asks Razorpay to end it, then writes FREE.
Verify-payment can apply a renewal in between, and the cancel used to land
over it: a period just paid for, wiped. Cancel now takes the billing lock
verify holds, re-reads, and refuses if the subscription moved.

SQLite has no advisory locks, so the renewal is committed from inside the
provider call — the window the lock-and-re-read closes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import update

from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.routers import subscriptions as subscriptions_router
from app.services import razorpay_client


@pytest.fixture()
def sub(db_session, business):
    sub = Subscription(
        business_id=business.id,
        tier=SubscriptionTier.PRO,
        status=SubscriptionStatus.ACTIVE,
        razorpay_subscription_id="sub_original",
        current_period_end=datetime.now(UTC) + timedelta(days=10),
    )
    db_session.add(sub)
    db_session.commit()
    return sub


def _cancel(auth_client, provider_call):
    with (
        patch.object(razorpay_client, "is_configured", return_value=True),
        patch.object(razorpay_client, "cancel_subscription", side_effect=provider_call),
    ):
        return auth_client.post("/api/v1/subscriptions/cancel")


class TestARenewalDuringTheCancel:
    def test_the_cancel_is_refused(self, auth_client, db_session, sub):
        def renewal_lands(_provider_id):
            db_session.execute(
                update(Subscription)
                .where(Subscription.id == sub.id)
                .values(
                    razorpay_subscription_id="pay_renewal",
                    current_period_end=datetime.now(UTC) + timedelta(days=40),
                )
            )
            db_session.commit()
            return {"status": "cancelled"}

        response = _cancel(auth_client, renewal_lands)

        assert response.status_code == 409, response.text
        assert "payment was applied" in response.json()["detail"]

    def test_the_renewal_is_kept(self, auth_client, db_session, sub):
        def renewal_lands(_provider_id):
            db_session.execute(
                update(Subscription)
                .where(Subscription.id == sub.id)
                .values(razorpay_subscription_id="pay_renewal")
            )
            db_session.commit()
            return {"status": "cancelled"}

        _cancel(auth_client, renewal_lands)

        db_session.refresh(sub)
        assert sub.tier is SubscriptionTier.PRO
        assert sub.status is SubscriptionStatus.ACTIVE
        assert sub.razorpay_subscription_id == "pay_renewal"


class TestAnUncontestedCancel:
    def test_it_still_cancels(self, auth_client, db_session, sub):
        response = _cancel(auth_client, lambda _id: {"status": "cancelled"})

        assert response.status_code == 200, response.text
        db_session.refresh(sub)
        assert sub.tier is SubscriptionTier.FREE
        assert sub.status is SubscriptionStatus.CANCELLED

    def test_it_takes_the_billing_lock_after_the_provider_call(
        self, monkeypatch, auth_client, business, sub
    ):
        order = []
        monkeypatch.setattr(
            subscriptions_router, "_serialise_billing",
            lambda db, bid: order.append(("lock", bid)),
        )

        _cancel(auth_client, lambda _id: (order.append("provider"), {"status": "cancelled"})[1])

        assert order == ["provider", ("lock", business.id)]
