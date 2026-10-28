"""C103 Pass 14, M3: state-machine and lifecycle tests.

Every subscription transition the product allows, driven end-to-end through
the API, with the feature gates verified at each state.
"""
from __future__ import annotations

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
    def test_paying_for_a_lower_tier_takes_it(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, tier="enterprise", payment="pay_e")
        assert _row(db_session, business.id).tier == SubscriptionTier.ENTERPRISE

        _pay(auth_client, business.id, tier="pro", payment="pay_p")
        sub = _row(db_session, business.id)
        assert sub.tier == SubscriptionTier.PRO
        assert sub.status == SubscriptionStatus.ACTIVE


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
            "created_at": int(ended.timestamp()) + 60,
        }
        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=order):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_x",
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

        resp = auth_client.post(CANCEL)
        assert resp.status_code == 200
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
            "created_at": int(ended.timestamp()) + 60,
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=fresh):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_x",
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
            "created_at": int(ended.timestamp()),
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=same_second):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_x",
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
            "created_at": int(ended.timestamp()) - 3600,
        }

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=stale):
            resp = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_x",
                    "razorpay_payment_id": "pay_stale",
                    "razorpay_signature": "sig",
                    "tier": "pro",
                },
            )
        assert resp.status_code == 409
