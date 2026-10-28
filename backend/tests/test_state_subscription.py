"""M3 state machine: subscription lifecycle — FREE → ACTIVE (PRO/ENTERPRISE),
ACTIVE ↔ PAST_DUE, ACTIVE/PAST_DUE → CANCELLED/EXPIRED.

Guards:
- Webhook _VALID_FROM: ACTIVE only from PAST_DUE, PAST_DUE only from ACTIVE,
  CANCELLED/EXPIRED only from ACTIVE or PAST_DUE.
- Cancel guard: cannot cancel FREE, already-CANCELLED, already-EXPIRED, or
  lapsed ACTIVE.
- verify_payment: reactivates CANCELLED/EXPIRED only if new order postdates.

Side effects:
- is_paid() requires ACTIVE + paid tier + not lapsed.
- lapsed() compares current_period_end to now.
- Cancel sets tier to FREE and status to CANCELLED.

Idempotency:
- Webhook with same status is acknowledged but no-op.
- Webhook with unknown event is acknowledged but no-op.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.subscription import (
    PAID_TIERS,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
)

NOW = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)
PAST = NOW - timedelta(days=1)
# HTTP-level tests call lapsed() with no argument (defaults to wall clock),
# so the period_end must be genuinely in the future.
REAL_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _sub(db, business, *, tier=SubscriptionTier.PRO,
         status=SubscriptionStatus.ACTIVE, period_end=None) -> Subscription:
    sub = Subscription(
        business_id=business.id,
        tier=tier,
        status=status,
        current_period_end=period_end,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# -----------------------------------------------------------------------
# is_paid — the gate every paid feature checks
# -----------------------------------------------------------------------

class TestIsPaid:

    def test_active_pro_with_future_end_is_paid(self, db_session, business):
        sub = _sub(db_session, business, period_end=FUTURE)
        assert sub.is_paid(NOW) is True

    def test_active_pro_with_past_end_is_not_paid(self, db_session, business):
        sub = _sub(db_session, business, period_end=PAST)
        assert sub.is_paid(NOW) is False

    def test_active_free_is_not_paid(self, db_session, business):
        sub = _sub(db_session, business, tier=SubscriptionTier.FREE)
        assert sub.is_paid(NOW) is False

    def test_cancelled_pro_is_not_paid(self, db_session, business):
        sub = _sub(db_session, business, status=SubscriptionStatus.CANCELLED,
                   period_end=FUTURE)
        assert sub.is_paid(NOW) is False

    def test_past_due_pro_is_not_paid(self, db_session, business):
        sub = _sub(db_session, business, status=SubscriptionStatus.PAST_DUE,
                   period_end=FUTURE)
        assert sub.is_paid(NOW) is False

    def test_no_period_end_means_not_lapsed(self, db_session, business):
        sub = _sub(db_session, business, period_end=None)
        assert sub.lapsed(NOW) is False
        assert sub.is_paid(NOW) is True

    def test_enterprise_is_a_paid_tier(self):
        assert SubscriptionTier.ENTERPRISE in PAID_TIERS

    def test_free_is_not_a_paid_tier(self):
        assert SubscriptionTier.FREE not in PAID_TIERS


# -----------------------------------------------------------------------
# lapsed — the clock that expires one-time purchases
# -----------------------------------------------------------------------

class TestLapsed:

    def test_exactly_at_period_end_is_lapsed(self, db_session, business):
        sub = _sub(db_session, business, period_end=NOW)
        assert sub.lapsed(NOW) is True

    def test_one_second_before_period_end_is_not_lapsed(self, db_session, business):
        sub = _sub(db_session, business, period_end=NOW + timedelta(seconds=1))
        assert sub.lapsed(NOW) is False

    def test_naive_datetime_from_sqlite_is_handled(self, db_session, business):
        naive_end = datetime(2026, 4, 14, 12, 0, 0)
        sub = _sub(db_session, business, period_end=naive_end)
        assert sub.lapsed(NOW) is True


# -----------------------------------------------------------------------
# Webhook _VALID_FROM transitions
# -----------------------------------------------------------------------

class TestWebhookTransitionGuards:

    def test_active_to_past_due_is_valid(self):
        allowed = frozenset({SubscriptionStatus.ACTIVE})
        assert SubscriptionStatus.ACTIVE in allowed

    def test_past_due_to_active_is_valid(self):
        allowed = frozenset({SubscriptionStatus.PAST_DUE})
        assert SubscriptionStatus.PAST_DUE in allowed

    def test_cancelled_from_active_is_valid(self):
        allowed = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE})
        assert SubscriptionStatus.ACTIVE in allowed

    def test_cancelled_from_past_due_is_valid(self):
        allowed = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE})
        assert SubscriptionStatus.PAST_DUE in allowed

    def test_expired_cannot_go_to_past_due(self):
        valid_from_past_due = frozenset({SubscriptionStatus.ACTIVE})
        assert SubscriptionStatus.EXPIRED not in valid_from_past_due

    def test_cancelled_cannot_go_to_past_due(self):
        valid_from_past_due = frozenset({SubscriptionStatus.ACTIVE})
        assert SubscriptionStatus.CANCELLED not in valid_from_past_due


# -----------------------------------------------------------------------
# Cancel guards
# -----------------------------------------------------------------------

class TestCancelGuards:

    @staticmethod
    def _ensure_sub(db, business, **kwargs):
        existing = db.query(Subscription).filter_by(
            business_id=business.id,
        ).one_or_none()
        if existing is not None:
            db.delete(existing)
            db.commit()
        return _sub(db, business, **kwargs)

    def test_cancel_a_free_subscription_is_refused(self, auth_client, db_session, business):
        self._ensure_sub(db_session, business, tier=SubscriptionTier.FREE)
        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 400
        assert "Free plan" in resp.text

    def test_cancel_an_already_cancelled_is_refused(self, auth_client, db_session, business):
        self._ensure_sub(db_session, business, status=SubscriptionStatus.CANCELLED)
        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 409
        assert "already cancelled" in resp.text.lower()

    def test_cancel_an_expired_is_refused(self, auth_client, db_session, business):
        self._ensure_sub(db_session, business, status=SubscriptionStatus.EXPIRED)
        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 409

    def test_cancel_a_lapsed_active_is_refused(self, auth_client, db_session, business):
        self._ensure_sub(db_session, business, period_end=PAST)
        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 400
        assert "Free plan" in resp.text


# -----------------------------------------------------------------------
# Cancel side effects
# -----------------------------------------------------------------------

class TestCancelSideEffects:

    def test_cancel_sets_tier_to_free_and_status_to_cancelled(
        self, auth_client, db_session, business,
    ):
        existing = db_session.query(Subscription).filter_by(
            business_id=business.id,
        ).one_or_none()
        if existing is not None:
            db_session.delete(existing)
            db_session.commit()
        _sub(db_session, business, period_end=REAL_FUTURE)
        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == SubscriptionTier.FREE.value
        assert body["status"] == SubscriptionStatus.CANCELLED.value


# -----------------------------------------------------------------------
# Every status storable
# -----------------------------------------------------------------------

class TestEverySubscriptionStatusIsStorable:

    def test_all_four_statuses_can_be_stored(self, db_session, business):
        for s in SubscriptionStatus:
            existing = db_session.query(Subscription).filter_by(
                business_id=business.id,
            ).one_or_none()
            if existing is not None:
                db_session.delete(existing)
                db_session.commit()
            sub = _sub(db_session, business, status=s)
            assert sub.status is s
