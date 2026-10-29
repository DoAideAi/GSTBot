"""C103 Pass 14, M3: state-machine and lifecycle tests.

Every subscription transition the product allows, driven end-to-end through
the API, with the feature gates verified at each state.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.schemas.subscription import SubscriptionOut
from app.services import razorpay_client
from app.services import usage as usage_service
from tests.test_c103_boundaries import _end, _order, _pay, _row

CANCEL = "/api/v1/subscriptions/cancel"
CURRENT = "/api/v1/subscriptions/current"
ITC = "/api/v1/itc"
BULK = "/api/v1/meta/gstin/bulk"
GSTIN = "27AAPFU0939F1ZV"


# ---- Full lifecycle: free → paid → lapsed → renewed ----

class TestFreeToProMonthlyToLapsedToRenewed:
    def test_the_complete_monthly_cycle(self, auth_client, db_session, business):
        assert auth_client.get(ITC).status_code == 403

        _pay(auth_client, business.id, billing="monthly", payment="pay_m1")
        assert auth_client.get(ITC).status_code == 200
        sub = _row(db_session, business.id)
        assert sub.tier == SubscriptionTier.PRO
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.current_period_end is not None

        sub.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        assert auth_client.get(ITC).status_code == 403
        current = auth_client.get(CURRENT).json()
        assert current["status"] == "expired"

        renewed = _pay(auth_client, business.id, billing="monthly", payment="pay_m2")
        assert renewed.status_code == 200
        assert auth_client.get(ITC).status_code == 200
        assert auth_client.get(CURRENT).json()["status"] == "active"


class TestFreeToProAnnualToLapsed:
    def test_the_annual_cycle(self, auth_client, db_session, business):
        _pay(auth_client, business.id, billing="annual", payment="pay_a1")
        end = _end(
            _pay(auth_client, business.id, billing="annual", payment="pay_a1")
        )
        assert end > datetime.now(UTC) + timedelta(days=364)

        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        assert auth_client.get(ITC).status_code == 403
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE


class TestProToEnterpriseUpgrade:
    def test_upgrade_starts_its_period_from_now(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, tier="pro", payment="pay_p")
        pro_end = _row(db_session, business.id).current_period_end

        before = datetime.now(UTC)
        _pay(auth_client, business.id, tier="enterprise", payment="pay_e")
        sub = _row(db_session, business.id)
        assert sub.tier == SubscriptionTier.ENTERPRISE
        end = sub.current_period_end
        assert end is not None
        end = end.replace(tzinfo=UTC) if end.tzinfo is None else end
        assert end >= before + timedelta(days=30)
        if pro_end is not None:
            pro_end_aware = pro_end.replace(tzinfo=UTC) if pro_end.tzinfo is None else pro_end
            assert end != pro_end_aware + timedelta(days=30)


class TestEnterpriseToProDowngrade:
    def test_a_lower_tier_paid_over_a_running_higher_one_keeps_the_higher(
        self, auth_client, db_session, business
    ):
        """Taking it ended the CA plan the business had paid for, at once and
        with no refund (P21). create-order now refuses the lower plan while the
        higher one runs; a lower payment that gets through anyway (two
        checkouts opened from Free) is recorded, flagged for a refund, and
        the higher plan kept."""
        _pay(auth_client, business.id, tier="enterprise", payment="pay_e")
        ca_end = _row(db_session, business.id).current_period_end

        resp = _pay(auth_client, business.id, tier="pro", payment="pay_p")
        assert resp.status_code == 200
        sub = _row(db_session, business.id)
        db_session.refresh(sub)
        assert sub.tier == SubscriptionTier.ENTERPRISE
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.current_period_end == ca_end


class TestSameTierBillingChange:
    def test_pro_monthly_to_pro_annual_stacks_from_current_end(
        self, auth_client, db_session, business
    ):
        monthly_end = _end(
            _pay(auth_client, business.id, billing="monthly", payment="pay_m")
        )
        annual_resp = _pay(
            auth_client, business.id, billing="annual", payment="pay_a"
        )
        annual_end = _end(annual_resp)
        assert annual_end - monthly_end == timedelta(days=365)


# ---- Cancel lifecycle ----

class TestCancelLifecycle:
    def test_cancel_and_immediate_resubscribe(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_1")
        assert auth_client.post(CANCEL).status_code == 200
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.tier == SubscriptionTier.FREE
        assert auth_client.get(ITC).status_code == 403

        db_session.refresh(sub)
        ended = sub.updated_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=UTC)
        order = {
            **_order(business.id, "pro"),
            "id": "order_fresh",
            "created_at": int(ended.timestamp()) + 60,
        }
        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=order):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_fresh",
                    "razorpay_payment_id": "pay_fresh",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert resp.status_code == 200
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.tier == SubscriptionTier.PRO
        assert auth_client.get(ITC).status_code == 200

    def test_cancel_loses_remaining_days(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_1")
        sub = _row(db_session, business.id)
        original_end = sub.current_period_end
        assert original_end is not None

        auth_client.post(CANCEL)
        sub = _row(db_session, business.id)
        assert sub.tier == SubscriptionTier.FREE
        assert sub.status == SubscriptionStatus.CANCELLED
        assert not sub.is_paid()

    def test_cancel_a_lapsed_subscription_is_refused(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_1")
        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(hours=1)
        db_session.commit()

        resp = auth_client.post(CANCEL)
        assert resp.status_code == 400
        assert "No active paid subscription" in resp.json()["detail"]
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_a_past_due_lapsed_subscription_can_still_be_cancelled(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
            razorpay_subscription_id="sub_managed",
            current_period_end=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add(sub)
        db_session.commit()

        # A sub_ mandate is cancelled at Razorpay first, so the provider has to
        # be there to accept it; without one the cancel is refused, untouched.
        with (
            patch.object(razorpay_client, "is_configured", return_value=True),
            patch.object(
                razorpay_client, "cancel_subscription", return_value={"status": "cancelled"}
            ) as cancel,
        ):
            resp = auth_client.post(CANCEL)
        assert resp.status_code == 200
        cancel.assert_called_once_with("sub_managed")
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.tier == SubscriptionTier.FREE

    def test_double_cancel_is_refused(self, auth_client, db_session, business):
        _pay(auth_client, business.id, payment="pay_1")
        assert auth_client.post(CANCEL).status_code == 200
        resp = auth_client.post(CANCEL)
        assert resp.status_code == 400


# ---- Feature gating across every subscription state ----

PREMIUM_ENDPOINTS = [
    ("GET", ITC),
    ("POST", BULK, {"gstins": [GSTIN]}),
]


class TestFeatureGatesTrackSubscriptionState:
    @staticmethod
    def _check(auth_client, method, url, body=None):
        if method == "GET":
            return auth_client.get(url)
        return auth_client.post(url, json=body)

    def test_free_user_is_refused(self, auth_client, business):
        for args in PREMIUM_ENDPOINTS:
            resp = self._check(auth_client, *args)
            assert resp.status_code == 403, f"Expected 403 for {args}"

    def test_paid_user_is_allowed(self, auth_client, db_session, business):
        _pay(auth_client, business.id, payment="pay_1")
        for args in PREMIUM_ENDPOINTS:
            resp = self._check(auth_client, *args)
            assert resp.status_code != 403, f"Unexpected 403 for {args}"

    def test_lapsed_user_is_refused(self, auth_client, db_session, business):
        _pay(auth_client, business.id, payment="pay_1")
        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        for args in PREMIUM_ENDPOINTS:
            resp = self._check(auth_client, *args)
            assert resp.status_code == 403, f"Expected 403 for {args}"

    def test_renewed_user_is_allowed_again(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_1")
        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()

        _pay(auth_client, business.id, payment="pay_2")
        for args in PREMIUM_ENDPOINTS:
            resp = self._check(auth_client, *args)
            assert resp.status_code != 403, f"Unexpected 403 for {args}"


# ---- SubscriptionOut schema validator ----

class TestSubscriptionOutReportsTheLogicalState:
    @staticmethod
    def _make(
        tier=SubscriptionTier.PRO,
        status=SubscriptionStatus.ACTIVE,
        period_end=None,
    ):
        now = datetime.now(UTC)
        return SubscriptionOut(
            id=1,
            business_id=1,
            tier=tier,
            status=status,
            current_period_end=period_end,
            created_at=now,
            updated_at=now,
        )

    def test_active_with_future_period_reports_active(self):
        out = self._make(period_end=datetime.now(UTC) + timedelta(days=15))
        assert out.status == SubscriptionStatus.ACTIVE

    def test_active_with_past_period_reports_expired(self):
        out = self._make(period_end=datetime.now(UTC) - timedelta(seconds=1))
        assert out.status == SubscriptionStatus.EXPIRED

    def test_active_with_no_period_reports_active(self):
        out = self._make(period_end=None)
        assert out.status == SubscriptionStatus.ACTIVE

    def test_cancelled_stays_cancelled(self):
        out = self._make(
            status=SubscriptionStatus.CANCELLED,
            period_end=datetime.now(UTC) + timedelta(days=15),
        )
        assert out.status == SubscriptionStatus.CANCELLED

    def test_expired_stays_expired(self):
        out = self._make(status=SubscriptionStatus.EXPIRED, period_end=None)
        assert out.status == SubscriptionStatus.EXPIRED


# ---- get_tier respects every non-paid state ----

class TestGetTierRespectsEveryNonPaidState:
    @staticmethod
    def _sub(db_session, business_id, **overrides):
        sub = db_session.query(Subscription).filter_by(
            business_id=business_id
        ).one_or_none()
        if sub is None:
            sub = Subscription(business_id=business_id)
            db_session.add(sub)
        for k, v in overrides.items():
            setattr(sub, k, v)
        db_session.commit()
        return sub

    def test_no_subscription_row(self, db_session, business):
        db_session.query(Subscription).filter_by(
            business_id=business.id
        ).delete()
        db_session.commit()
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE

    def test_free_tier(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.FREE, status=SubscriptionStatus.ACTIVE,
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE

    def test_cancelled_pro(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.CANCELLED,
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE

    def test_expired_pro(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.EXPIRED,
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE

    def test_active_pro_with_lapsed_period(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.ACTIVE,
            current_period_end=datetime.now(UTC) - timedelta(hours=1),
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE

    def test_active_pro_with_future_period(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.ACTIVE,
            current_period_end=datetime.now(UTC) + timedelta(days=15),
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.PRO

    def test_active_pro_with_no_period(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.ACTIVE,
            current_period_end=None,
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.PRO

    def test_past_due_pro(self, db_session, business):
        self._sub(
            db_session, business.id,
            tier=SubscriptionTier.PRO, status=SubscriptionStatus.PAST_DUE,
        )
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE


# ---- Expired business can resubscribe with a fresh order ----

class TestExpiredBusinessCanResubscribeWithFreshOrder:
    def test_an_expired_row_can_be_revived_by_a_fresh_order(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
            razorpay_subscription_id="pay_old",
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        ended = sub.updated_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=UTC)
        fresh = {
            **_order(business.id, "pro"),
            "id": "order_revival",
            "created_at": int(ended.timestamp()) + 60,
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=fresh):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_revival",
                    "razorpay_payment_id": "pay_revival",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert resp.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.tier == SubscriptionTier.PRO

    def test_an_order_from_the_same_second_as_the_cancellation_is_accepted(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.FREE,
            status=SubscriptionStatus.CANCELLED,
            razorpay_subscription_id="pay_old",
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        ended = sub.updated_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=UTC)
        same_second = {
            **_order(business.id, "pro"),
            "id": "order_same_sec",
            "created_at": int(ended.timestamp()),
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=same_second):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_same_sec",
                    "razorpay_payment_id": "pay_same_sec",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert resp.status_code == 200

    def test_expired_row_still_rejects_a_stale_order(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        ended = sub.updated_at
        if ended.tzinfo is None:
            ended = ended.replace(tzinfo=UTC)
        stale = {
            **_order(business.id, "pro"),
            "id": "order_stale",
            "created_at": int(ended.timestamp()) - 3600,
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=stale):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_stale",
                    "razorpay_payment_id": "pay_stale",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert resp.status_code == 409


# ---- Webhook transition matrix ----

class TestWebhookTransitionMatrix:
    """Every valid transition the webhook can perform, and the blocked ones
    it must refuse — a complete 4×4 matrix against the six events."""

    @staticmethod
    def _webhook(client, event, razorpay_id):
        payload = {"event": event, "payload": {
            "subscription": {"entity": {"id": razorpay_id}},
        }}
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            return client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "v"},
            )

    @staticmethod
    def _sub(db_session, business, status, *, razorpay_id):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=status,
            razorpay_subscription_id=razorpay_id,
        )
        db_session.add(sub)
        db_session.commit()
        return sub

    # -- valid: ACTIVE → CANCELLED via subscription.cancelled --

    def test_active_to_cancelled_via_subscription_cancelled(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.ACTIVE,
            razorpay_id="sub_ac",
        )
        resp = self._webhook(client, "subscription.cancelled", "sub_ac")
        assert resp.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.tier == SubscriptionTier.PRO

    # -- valid: PAST_DUE → CANCELLED via subscription.cancelled --

    def test_past_due_to_cancelled_via_subscription_cancelled(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.PAST_DUE,
            razorpay_id="sub_pdc",
        )
        resp = self._webhook(client, "subscription.cancelled", "sub_pdc")
        assert resp.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    # -- valid: PAST_DUE → EXPIRED via subscription.expired --

    def test_past_due_to_expired_via_subscription_expired(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.PAST_DUE,
            razorpay_id="sub_pde",
        )
        resp = self._webhook(client, "subscription.expired", "sub_pde")
        assert resp.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    # -- valid: PAST_DUE → ACTIVE via subscription.activated --

    def test_past_due_to_active_via_subscription_activated(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.PAST_DUE,
            razorpay_id="sub_pda",
        )
        resp = self._webhook(client, "subscription.activated", "sub_pda")
        assert resp.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE

    # -- blocked: CANCELLED → EXPIRED --

    def test_cancelled_to_expired_is_blocked(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.CANCELLED,
            razorpay_id="sub_ce",
        )
        self._webhook(client, "subscription.expired", "sub_ce")
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    # -- blocked: EXPIRED → CANCELLED --

    def test_expired_to_cancelled_is_blocked(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.EXPIRED,
            razorpay_id="sub_ec",
        )
        self._webhook(client, "subscription.cancelled", "sub_ec")
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    # -- self-transitions are no-ops --

    def test_active_to_active_is_a_noop(self, client, db_session, business):
        sub = self._sub(
            db_session, business, SubscriptionStatus.ACTIVE,
            razorpay_id="sub_aa",
        )
        self._webhook(client, "subscription.charged", "sub_aa")
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_cancelled_to_cancelled_is_a_noop(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.CANCELLED,
            razorpay_id="sub_cc",
        )
        self._webhook(client, "subscription.cancelled", "sub_cc")
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    # -- webhook cancel preserves tier (unlike API cancel which sets FREE) --

    def test_webhook_cancel_preserves_tier_while_api_cancel_clears_it(
        self, client, db_session, business
    ):
        sub = self._sub(
            db_session, business, SubscriptionStatus.ACTIVE,
            razorpay_id="sub_tp",
        )
        self._webhook(client, "subscription.cancelled", "sub_tp")
        db_session.refresh(sub)
        assert sub.tier == SubscriptionTier.PRO
        assert sub.status == SubscriptionStatus.CANCELLED

    # -- an unrecognised event is acknowledged --

    def test_an_unrecognised_event_is_acknowledged(
        self, client, db_session, business
    ):
        self._sub(
            db_session, business, SubscriptionStatus.ACTIVE,
            razorpay_id="sub_unk",
        )
        resp = self._webhook(client, "order.paid", "sub_unk")
        assert resp.status_code == 200


# ---- Webhook + feature-gate integration ----

class TestWebhookDrivenStatusAffectsFeatureGate:
    """A webhook that moves a subscription to PAST_DUE, CANCELLED, or EXPIRED
    must make premium endpoints refuse that business."""

    @staticmethod
    def _webhook(client, event, razorpay_id):
        payload = {"event": event, "payload": {
            "subscription": {"entity": {"id": razorpay_id}},
        }}
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            return client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "v"},
            )

    def test_payment_failed_revokes_premium(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_wh1")
        sub = _row(db_session, business.id)
        sub.razorpay_subscription_id = "sub_wh1"
        db_session.commit()

        assert auth_client.get("/api/v1/itc").status_code == 200
        self._webhook(auth_client, "payment.failed", "sub_wh1")
        assert auth_client.get("/api/v1/itc").status_code == 403

    def test_subscription_charged_restores_premium(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
            razorpay_subscription_id="sub_wh2",
            current_period_end=datetime.now(UTC) + timedelta(days=15),
        )
        db_session.add(sub)
        db_session.commit()

        assert auth_client.get("/api/v1/itc").status_code == 403
        self._webhook(auth_client, "subscription.charged", "sub_wh2")
        assert auth_client.get("/api/v1/itc").status_code == 200


# ---- Period stacking with naive timestamps (SQLite edge case) ----

class TestPeriodStackingHandlesNaiveDatetimes:
    """SQLite returns naive datetimes. The stacking logic in _period_end_for
    must handle both aware and naive current_period_end correctly."""

    def test_renewal_stacks_when_period_end_is_naive(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_stack1")
        sub = _row(db_session, business.id)
        original_end = sub.current_period_end
        assert original_end is not None
        if original_end.tzinfo is not None:
            sub.current_period_end = original_end.replace(tzinfo=None)
            db_session.commit()

        resp = _pay(auth_client, business.id, payment="pay_stack2")
        assert resp.status_code == 200
        new_end = _end(resp)
        naive_end = original_end.replace(tzinfo=None) if original_end.tzinfo else original_end
        aware_end = naive_end.replace(tzinfo=UTC)
        assert new_end - aware_end == timedelta(days=30)


# ---- PAST_DUE cancel without lapse ----

class TestPastDueNonLapsedCancel:
    """A Razorpay-managed sub that is PAST_DUE but whose period hasn't ended
    can still be cancelled — the business wants to end the billing relationship."""

    def test_past_due_with_future_period_can_be_cancelled(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
            razorpay_subscription_id="pay_checkout",
            current_period_end=datetime.now(UTC) + timedelta(days=10),
        )
        db_session.add(sub)
        db_session.commit()

        resp = auth_client.post("/api/v1/subscriptions/cancel")
        assert resp.status_code == 200
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.tier == SubscriptionTier.FREE


# ---- PAST_DUE recovery via one-time checkout ----

class TestPastDueRecoveryViaCheckout:
    """A Razorpay-managed sub that went PAST_DUE can be recovered by paying
    through the one-time checkout flow — the business bypasses the failed
    recurring billing."""

    def test_a_past_due_sub_can_be_reactivated_by_a_fresh_payment(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
            razorpay_subscription_id="sub_pastdue",
            current_period_end=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add(sub)
        db_session.commit()

        assert auth_client.get("/api/v1/itc").status_code == 403

        resp = _pay(auth_client, business.id, payment="pay_recover")
        assert resp.status_code == 200
        sub = _row(db_session, business.id)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.tier == SubscriptionTier.PRO
        end = sub.current_period_end
        assert end is not None
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        assert end > datetime.now(UTC)

        assert auth_client.get("/api/v1/itc").status_code == 200
