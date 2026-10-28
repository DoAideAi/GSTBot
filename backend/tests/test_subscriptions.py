"""Tests for subscription management, payment flow, and usage tracking."""
from __future__ import annotations

import logging
from datetime import UTC
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.services import razorpay_client
from app.services import usage as usage_service

# --------------------------------------------------------------------------
# Pricing (public endpoint)
# --------------------------------------------------------------------------

class TestPricing:
    def test_pricing_returns_all_tiers(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        assert response.status_code == 200
        data = response.json()
        assert "tiers" in data
        assert "free" in data["tiers"]
        assert "pro" in data["tiers"]
        assert "enterprise" in data["tiers"]

    def test_pricing_includes_razorpay_key(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        assert response.status_code == 200
        assert "razorpay_key_id" in response.json()

    def test_free_tier_has_zero_price(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        data = response.json()
        assert data["tiers"]["free"]["price_monthly"] == 0

    def test_pro_tier_costs_499(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        data = response.json()
        assert data["tiers"]["pro"]["price_monthly"] == 499_00

    def test_enterprise_tier_costs_2999(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        data = response.json()
        assert data["tiers"]["enterprise"]["price_monthly"] == 2999_00

    def test_each_tier_has_features(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        data = response.json()
        for tier in data["tiers"].values():
            assert len(tier["features"]) > 0

    def test_pricing_is_accessible_without_a_token(self, client):
        response = client.get("/api/v1/subscriptions/pricing")
        assert response.status_code == 200


# --------------------------------------------------------------------------
# Current subscription
# --------------------------------------------------------------------------

class TestCurrentSubscription:
    def test_no_subscription_returns_null(self, auth_client):
        response = auth_client.get("/api/v1/subscriptions/current")
        assert response.status_code == 200
        assert response.json() is None

    def test_returns_subscription_after_creation(self, auth_client, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()
        response = auth_client.get("/api/v1/subscriptions/current")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "pro"
        assert data["status"] == "active"

    def test_requires_authentication(self, client):
        response = client.get("/api/v1/subscriptions/current")
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Create order
# --------------------------------------------------------------------------

class TestCreateOrder:
    def test_free_tier_order_is_refused(self, auth_client):
        response = auth_client.post(
            "/api/v1/subscriptions/create-order",
            json={"tier": "free"},
        )
        assert response.status_code == 400

    def test_razorpay_not_configured_returns_503(self, auth_client):
        with patch.object(razorpay_client, "is_configured", return_value=False):
            response = auth_client.post(
                "/api/v1/subscriptions/create-order",
                json={"tier": "pro"},
            )
        assert response.status_code == 503

    def test_razorpay_failure_returns_502(self, auth_client):
        with (
            patch.object(razorpay_client, "is_configured", return_value=True),
            patch.object(razorpay_client, "create_order", return_value=None),
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/create-order",
                json={"tier": "pro"},
            )
        assert response.status_code == 502

    def test_successful_order_returns_order_details(self, auth_client):
        mock_order = {
            "id": "order_test123",
            "amount": 499_00,
            "currency": "INR",
        }
        with (
            patch.object(razorpay_client, "is_configured", return_value=True),
            patch.object(razorpay_client, "create_order", return_value=mock_order),
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/create-order",
                json={"tier": "pro"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == "order_test123"
        assert data["amount"] == 499_00
        assert data["tier"] == "pro"

    def test_requires_authentication(self, client):
        response = client.post(
            "/api/v1/subscriptions/create-order",
            json={"tier": "pro"},
        )
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Verify payment
# --------------------------------------------------------------------------

def _paid_order(business_id: int, tier: str) -> dict:
    """The order Razorpay returns for a checkout this business paid for."""
    t = SubscriptionTier(tier)
    amount = razorpay_client.TIER_PRICING[t]["price_monthly"]
    return {
        "id": "order_test",
        "receipt": razorpay_client.order_receipt(business_id, t),
        "amount": amount,
        "amount_paid": amount,
        "status": "paid",
    }


def _aware(moment):
    """SQLite hands timestamps back naive; they are UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


class TestVerifyPayment:
    def test_invalid_signature_is_refused(self, auth_client):
        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=False
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_test",
                    "razorpay_payment_id": "pay_test",
                    "razorpay_signature": "bad_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 400

    def test_valid_payment_creates_subscription(self, auth_client, db_session, business):
        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_test",
                    "razorpay_payment_id": "pay_test",
                    "razorpay_signature": "valid_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "pro"
        assert data["status"] == "active"
        assert data["business_id"] == business.id

    def test_valid_payment_upgrades_existing_subscription(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.FREE,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, "enterprise")
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_test",
                    "razorpay_payment_id": "pay_test",
                    "razorpay_signature": "valid_sig",
                    "tier": "enterprise",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "enterprise"

    def test_requires_authentication(self, client):
        response = client.post(
            "/api/v1/subscriptions/verify-payment",
            json={
                "razorpay_order_id": "order_test",
                "razorpay_payment_id": "pay_test",
                "razorpay_signature": "sig",
                "tier": "pro",
            },
        )
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Cancel subscription
# --------------------------------------------------------------------------

class TestCancelSubscription:
    def test_cancelling_free_tier_is_refused(self, auth_client):
        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 400

    def test_cancelling_paid_subscription_reverts_to_free(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()

        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "free"
        assert data["status"] == "cancelled"

    def test_a_one_time_payment_cancels_without_asking_razorpay(
        self, auth_client, db_session, business
    ):
        """Checkout stores a payment id; there is no provider subscription to end."""
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id="pay_onetime123",
        )
        db_session.add(sub)
        db_session.commit()

        with (
            patch.object(razorpay_client, "is_configured", return_value=True),
            patch.object(razorpay_client, "cancel_subscription", return_value=None) as cancel,
        ):
            response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 200, response.text
        cancel.assert_not_called()
        db_session.refresh(sub)
        assert sub.tier == SubscriptionTier.FREE
        assert sub.status == SubscriptionStatus.CANCELLED

    def test_razorpay_failure_blocks_local_cancel(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id="sub_test_fail",
        )
        db_session.add(sub)
        db_session.commit()

        with (
            patch.object(razorpay_client, "is_configured", return_value=True),
            patch.object(razorpay_client, "cancel_subscription", return_value=None),
        ):
            response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 502
        db_session.refresh(sub)
        assert sub.tier == SubscriptionTier.PRO
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_cancelling_already_cancelled_is_refused(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.CANCELLED,
        )
        db_session.add(sub)
        db_session.commit()

        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 409
        assert "already cancelled" in response.json()["detail"]

    def test_cancelling_expired_is_refused(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
        )
        db_session.add(sub)
        db_session.commit()

        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 409
        assert "already expired" in response.json()["detail"]

    def test_cancelling_past_due_is_allowed(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
        )
        db_session.add(sub)
        db_session.commit()

        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "free"
        assert data["status"] == "cancelled"

    def test_requires_authentication(self, client):
        response = client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Usage tracking
# --------------------------------------------------------------------------

class TestUsageSummary:
    def test_empty_usage_returns_empty_list(self, auth_client):
        response = auth_client.get("/api/v1/subscriptions/usage")
        assert response.status_code == 200
        data = response.json()
        assert data["usage"] == []
        assert data["tier"] == "free"

    def test_records_show_in_summary(self, auth_client, db_session, business):
        usage_service.record_usage(db_session, business.id, "gst_lookup", 3)
        db_session.commit()

        response = auth_client.get("/api/v1/subscriptions/usage")
        assert response.status_code == 200
        data = response.json()
        assert len(data["usage"]) == 1
        assert data["usage"][0]["endpoint"] == "gst_lookup"
        assert data["usage"][0]["call_count"] == 3

    def test_requires_authentication(self, client):
        response = client.get("/api/v1/subscriptions/usage")
        assert response.status_code == 401


# --------------------------------------------------------------------------
# Usage service unit tests
# --------------------------------------------------------------------------

class TestUsageService:
    def test_record_usage_creates_new_row(self, db_session, business):
        row = usage_service.record_usage(db_session, business.id, "gst_lookup")
        assert row.call_count == 1

    def test_record_usage_increments_existing(self, db_session, business):
        usage_service.record_usage(db_session, business.id, "gst_lookup", 2)
        row = usage_service.record_usage(db_session, business.id, "gst_lookup", 3)
        assert row.call_count == 5

    def test_check_limit_allows_when_under(self, db_session, business):
        allowed, used, limit = usage_service.check_limit(
            db_session, business.id, "gst_lookup"
        )
        assert allowed is True
        assert used == 0
        assert limit == 5

    def test_check_limit_refuses_when_at_limit(self, db_session, business):
        usage_service.record_usage(db_session, business.id, "gst_lookup", 5)
        db_session.flush()
        allowed, used, limit = usage_service.check_limit(
            db_session, business.id, "gst_lookup"
        )
        assert allowed is False
        assert used == 5
        assert limit == 5

    def test_unlimited_endpoint_always_allowed(self, db_session, business):
        allowed, used, limit = usage_service.check_limit(
            db_session, business.id, "some_unknown_endpoint"
        )
        assert allowed is True
        assert limit == 0

    def test_get_tier_defaults_to_free(self, db_session, business):
        tier = usage_service.get_tier(db_session, business.id)
        assert tier == SubscriptionTier.FREE

    def test_get_tier_returns_subscription_tier(self, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.ENTERPRISE,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.flush()
        tier = usage_service.get_tier(db_session, business.id)
        assert tier == SubscriptionTier.ENTERPRISE

    def test_pro_tier_has_unlimited_lookups(self, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.flush()
        allowed, _, limit = usage_service.check_limit(
            db_session, business.id, "gst_lookup"
        )
        assert allowed is True
        assert limit == 0


# --------------------------------------------------------------------------
# Razorpay client unit tests
# --------------------------------------------------------------------------

class TestRazorpayClient:
    def test_not_configured_when_keys_empty(self):
        assert razorpay_client.is_configured() is False

    def test_create_order_returns_none_when_not_configured(self):
        result = razorpay_client.create_order(499_00)
        assert result is None

    def test_create_customer_returns_none_when_not_configured(self):
        result = razorpay_client.create_customer("test@example.com")
        assert result is None

    def test_verify_payment_signature_fails_without_secret(self):
        result = razorpay_client.verify_payment_signature(
            "order_id", "payment_id", "signature"
        )
        assert result is False

    def test_verify_webhook_signature_fails_without_secret(self):
        result = razorpay_client.verify_webhook_signature(b"body", "signature")
        assert result is False

    def test_cancel_subscription_returns_none_when_not_configured(self):
        result = razorpay_client.cancel_subscription("sub_test")
        assert result is None

    def test_fetch_subscription_returns_none_when_not_configured(self):
        result = razorpay_client.fetch_subscription("sub_test")
        assert result is None

    def test_tier_pricing_has_all_tiers(self):
        assert SubscriptionTier.FREE in razorpay_client.TIER_PRICING
        assert SubscriptionTier.PRO in razorpay_client.TIER_PRICING
        assert SubscriptionTier.ENTERPRISE in razorpay_client.TIER_PRICING


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------

class TestWebhook:
    def test_invalid_signature_is_refused(self, client):
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=False
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=b'{"event": "test"}',
                headers={"X-Razorpay-Signature": "bad"},
            )
        assert response.status_code == 401

    def test_valid_signature_acknowledged(self, client):
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=b'{"event": "test"}',
                headers={"X-Razorpay-Signature": "good"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_payment_failed_transitions_to_past_due(self, client, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id="pay_live123",
        )
        db_session.add(sub)
        db_session.commit()

        import json
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {"entity": {"id": "pay_live123"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.PAST_DUE

    def test_past_due_subscription_degrades_tier_to_free(self, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
        )
        db_session.add(sub)
        db_session.flush()
        tier = usage_service.get_tier(db_session, business.id)
        assert tier == SubscriptionTier.FREE

    def test_subscription_halted_transitions_to_past_due(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id="sub_halt1",
        )
        db_session.add(sub)
        db_session.commit()

        import json
        payload = {
            "event": "subscription.halted",
            "payload": {
                "subscription": {"entity": {"id": "sub_halt1"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.PAST_DUE

    def test_subscription_charged_reactivates_past_due(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
            razorpay_subscription_id="sub_react1",
        )
        db_session.add(sub)
        db_session.commit()

        import json
        payload = {
            "event": "subscription.charged",
            "payload": {
                "subscription": {"entity": {"id": "sub_react1"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_subscription_expired_transitions_to_expired(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id="sub_exp1",
        )
        db_session.add(sub)
        db_session.commit()

        import json
        payload = {
            "event": "subscription.expired",
            "payload": {
                "subscription": {"entity": {"id": "sub_exp1"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    def test_unknown_razorpay_id_is_a_harmless_noop(self, client):
        import json
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {"entity": {"id": "pay_nonexistent"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200

    def test_malformed_json_is_rejected(self, client):
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=b"not json at all",
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 400
        assert "not valid JSON" in response.json()["detail"]

    def test_unmatched_subscription_is_logged(self, client, caplog):
        import json
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {"entity": {"id": "pay_orphaned_999"}},
            },
        }
        with (
            patch.object(razorpay_client, "verify_webhook_signature", return_value=True),
            caplog.at_level(logging.WARNING, logger="app.routers.subscriptions"),
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        assert any(
            "unknown subscription" in r.message and r.razorpay_id == "pay_orphaned_999"
            for r in caplog.records
        )


# --------------------------------------------------------------------------
# GB032: Observability — subscription lifecycle audit trail
# --------------------------------------------------------------------------

class TestSubscriptionCancellationIsLogged:
    def test_cancellation_produces_an_audit_log_line(
        self, auth_client, db_session, business, caplog
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()

        with caplog.at_level(logging.INFO, logger="app.routers.subscriptions"):
            response = auth_client.post("/api/v1/subscriptions/cancel")

        assert response.status_code == 200
        assert any(
            "Subscription cancelled" in r.message
            and r.business_id == business.id
            and r.old_tier == "pro"
            for r in caplog.records
        )

    def test_cancellation_log_includes_user_id(
        self, auth_client, db_session, business, caplog
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.ENTERPRISE,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()

        with caplog.at_level(logging.INFO, logger="app.routers.subscriptions"):
            auth_client.post("/api/v1/subscriptions/cancel")

        log = next(
            r for r in caplog.records if "Subscription cancelled" in r.message
        )
        assert hasattr(log, "user_id")
        assert log.old_tier == "enterprise"


# --------------------------------------------------------------------------
# GB034: State machine — subscription transition guards
# --------------------------------------------------------------------------

class TestWebhookTransitionGuards:
    """Webhook must reject invalid state transitions."""

    def _send_webhook(self, client, event, razorpay_id):
        import json
        payload = {
            "event": event,
            "payload": {
                "subscription": {"entity": {"id": razorpay_id}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            return client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )

    def test_expired_cannot_go_to_past_due(self, client, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
            razorpay_subscription_id="sub_expired_guard",
        )
        db_session.add(sub)
        db_session.commit()

        response = self._send_webhook(client, "payment.failed", "sub_expired_guard")
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    def test_cancelled_cannot_be_reactivated_by_webhook(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.CANCELLED,
            razorpay_subscription_id="sub_cancel_guard",
        )
        db_session.add(sub)
        db_session.commit()

        response = self._send_webhook(
            client, "subscription.charged", "sub_cancel_guard"
        )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    def test_expired_cannot_be_reactivated_by_webhook(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
            razorpay_subscription_id="sub_exp_guard",
        )
        db_session.add(sub)
        db_session.commit()

        response = self._send_webhook(
            client, "subscription.activated", "sub_exp_guard"
        )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    def test_cancelled_cannot_go_to_past_due(self, client, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.CANCELLED,
            razorpay_subscription_id="sub_cancel_pd",
        )
        db_session.add(sub)
        db_session.commit()

        response = self._send_webhook(
            client, "subscription.halted", "sub_cancel_pd"
        )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    def test_invalid_transition_is_logged(
        self, client, db_session, business, caplog
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
            razorpay_subscription_id="sub_log_guard",
        )
        db_session.add(sub)
        db_session.commit()

        with caplog.at_level(logging.WARNING, logger="app.routers.subscriptions"):
            self._send_webhook(client, "subscription.charged", "sub_log_guard")

        assert any(
            "invalid transition" in r.message.lower()
            for r in caplog.records
        )


class TestVerifyPaymentTransitionGuards:
    """verify_payment must not reactivate cancelled/expired subscriptions."""

    def test_cancelled_subscription_rejects_payment(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.CANCELLED,
        )
        db_session.add(sub)
        db_session.commit()

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, "enterprise")
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_stale",
                    "razorpay_payment_id": "pay_stale",
                    "razorpay_signature": "valid_sig",
                    "tier": "enterprise",
                },
            )
        assert response.status_code == 409
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED
        assert sub.tier == SubscriptionTier.PRO

    def test_expired_subscription_rejects_payment(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
        )
        db_session.add(sub)
        db_session.commit()

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_old",
                    "razorpay_payment_id": "pay_old",
                    "razorpay_signature": "valid_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 409
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.EXPIRED

    def test_cancelled_business_can_pay_again_with_a_fresh_order(
        self, auth_client, db_session, business
    ):
        # The refusal is for stale payments. A business that cancelled and then
        # bought again — an order Razorpay created after the cancellation — was
        # refused too, and told to create a new order, which met the same 409.
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.FREE,
            status=SubscriptionStatus.CANCELLED,
            razorpay_subscription_id="pay_original",
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        ended = _aware(sub.updated_at)
        fresh = {**_paid_order(business.id, "pro"), "created_at": int(ended.timestamp()) + 60}

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=fresh):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_new",
                    "razorpay_payment_id": "pay_new",
                    "razorpay_signature": "valid_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 200, response.text
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.tier == SubscriptionTier.PRO
        assert sub.razorpay_subscription_id == "pay_new"

    def test_order_older_than_the_cancellation_is_still_refused(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.FREE,
            status=SubscriptionStatus.CANCELLED,
        )
        db_session.add(sub)
        db_session.commit()
        db_session.refresh(sub)
        ended = _aware(sub.updated_at)
        stale = {**_paid_order(business.id, "pro"), "created_at": int(ended.timestamp()) - 3600}

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(razorpay_client, "fetch_order", return_value=stale):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_old",
                    "razorpay_payment_id": "pay_old",
                    "razorpay_signature": "valid_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 409
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED

    def test_past_due_subscription_can_be_reactivated(
        self, auth_client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.PAST_DUE,
        )
        db_session.add(sub)
        db_session.commit()

        with patch.object(
            razorpay_client, "verify_payment_signature", return_value=True
        ), patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, "pro")
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_retry",
                    "razorpay_payment_id": "pay_retry",
                    "razorpay_signature": "valid_sig",
                    "tier": "pro",
                },
            )
        assert response.status_code == 200
        db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.ACTIVE


# --------------------------------------------------------------------------
# GB036: Fence audit — billing ops require owner role
# --------------------------------------------------------------------------

class TestBillingOpsRequireOwner:
    """Subscription billing operations must not be accessible to accountants.

    An accountant linked to manage invoices should not be able to change what
    the business pays — create orders, verify payments, or cancel the plan.
    These are billing decisions, not bookkeeping.
    """

    @pytest.fixture()
    def accountant_client(self, auth_client, db_session):
        from app.models.user import User, UserRole
        from tests.conftest import TEST_EMAIL
        user = db_session.scalar(select(User).where(User.email == TEST_EMAIL))
        user.role = UserRole.ACCOUNTANT
        db_session.commit()
        return auth_client

    def test_accountant_cannot_create_order(self, accountant_client):
        response = accountant_client.post(
            "/api/v1/subscriptions/create-order",
            json={"tier": "pro"},
        )
        assert response.status_code == 403, response.text

    def test_accountant_cannot_verify_payment(self, accountant_client):
        response = accountant_client.post(
            "/api/v1/subscriptions/verify-payment",
            json={
                "razorpay_order_id": "order_test",
                "razorpay_payment_id": "pay_test",
                "razorpay_signature": "sig",
                "tier": "pro",
            },
        )
        assert response.status_code == 403, response.text

    def test_accountant_cannot_cancel_subscription(self, accountant_client):
        response = accountant_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 403, response.text

    def test_owner_can_still_create_order(self, auth_client):
        with patch.object(razorpay_client, "is_configured", return_value=False):
            response = auth_client.post(
                "/api/v1/subscriptions/create-order",
                json={"tier": "pro"},
            )
        assert response.status_code != 403

    def test_owner_can_still_cancel(self, auth_client, db_session, business):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
        db_session.commit()
        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 200

    def test_viewer_is_still_refused(self, auth_client, db_session):
        from app.models.user import User, UserRole
        from tests.conftest import TEST_EMAIL
        user = db_session.scalar(select(User).where(User.email == TEST_EMAIL))
        user.role = UserRole.VIEWER
        db_session.commit()
        response = auth_client.post("/api/v1/subscriptions/cancel")
        assert response.status_code == 403


# --------------------------------------------------------------------------
# GB036: Fence audit — webhook responses are uniform
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# GB036: Fence audit — cancel has its own rate-limit bucket
# --------------------------------------------------------------------------

class TestCancelHasSeparateRateLimit:
    """Cancel and verify-payment must not share a rate-limit bucket.

    When they shared ``_verify_limit``, exhausting one endpoint's budget
    starved the other — an attacker could spam cancel to block legitimate
    payment verification.
    """

    def test_cancel_uses_its_own_bucket_name(self):
        from app.routers.subscriptions import _cancel_limit, _verify_limit
        assert _cancel_limit.name != _verify_limit.name


# --------------------------------------------------------------------------
# GB036: Fence audit — webhook responses are uniform
# --------------------------------------------------------------------------

class TestWebhookResponsesAreUniform:
    """Webhook must not leak internal state through varying response bodies."""

    def test_no_entity_returns_generic_ok(self, client):
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=b'{"event": "test"}',
                headers={"X-Razorpay-Signature": "good"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok"}

    def test_unknown_subscription_returns_generic_ok(self, client):
        import json
        payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {"entity": {"id": "pay_nonexistent"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok"}
        assert "detail" not in body

    def test_invalid_transition_returns_generic_ok(
        self, client, db_session, business
    ):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.EXPIRED,
            razorpay_subscription_id="sub_uniform_test",
        )
        db_session.add(sub)
        db_session.commit()

        import json
        payload = {
            "event": "subscription.charged",
            "payload": {
                "subscription": {"entity": {"id": "sub_uniform_test"}},
            },
        }
        with patch.object(
            razorpay_client, "verify_webhook_signature", return_value=True
        ):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=json.dumps(payload).encode(),
                headers={"X-Razorpay-Signature": "valid"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok"}
        assert "detail" not in body


class TestPaymentVerificationFailureIsLogged:
    def test_a_failed_signature_produces_a_warning(
        self, auth_client, business, caplog
    ):
        with (
            patch.object(razorpay_client, "verify_payment_signature", return_value=False),
            caplog.at_level(logging.WARNING, logger="app.routers.subscriptions"),
        ):
            response = auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_suspect",
                    "razorpay_payment_id": "pay_suspect",
                    "razorpay_signature": "bad_sig",
                    "tier": "pro",
                },
            )

        assert response.status_code == 400
        assert any(
            "signature verification failed" in r.message
            and r.razorpay_order_id == "order_suspect"
            and r.business_id == business.id
            for r in caplog.records
        )


class TestPaymentPathLeavesARecord:
    """GB081: outcomes on the payment path that used to write nothing down."""

    def test_a_refused_signature_is_logged(self, client, caplog):
        with patch.object(razorpay_client, "verify_webhook_signature", return_value=False):
            client.post(
                "/api/v1/subscriptions/webhook",
                content=b'{"event": "x"}',
                headers={"X-Razorpay-Signature": "bad"},
            )
        [line] = [r for r in caplog.records if "signature did not verify" in r.getMessage()]
        assert line.levelname == "WARNING"
        assert line.has_signature is True

    def test_an_event_that_changes_nothing_is_logged(self, client, db_session, business, caplog):
        import json
        import logging

        db_session.add(
            Subscription(
                business_id=business.id,
                tier=SubscriptionTier.PRO,
                status=SubscriptionStatus.ACTIVE,
                razorpay_subscription_id="sub_noop1",
            )
        )
        db_session.commit()
        body = json.dumps(
            {
                "event": "subscription.charged",
                "payload": {"subscription": {"entity": {"id": "sub_noop1"}}},
            }
        ).encode()
        with (
            patch.object(razorpay_client, "verify_webhook_signature", return_value=True),
            caplog.at_level(logging.INFO, logger="app.routers.subscriptions"),
        ):
            resp = client.post(
                "/api/v1/subscriptions/webhook", content=body, headers={"X-Razorpay-Signature": "v"}
            )
        assert resp.status_code == 200
        [line] = [r for r in caplog.records if "without a status change" in r.getMessage()]
        assert line.reason == "already in that status"
        assert line.event == "subscription.charged"

    def test_checkout_without_razorpay_is_logged(self, auth_client, caplog):
        with patch.object(razorpay_client, "is_configured", return_value=False):
            resp = auth_client.post("/api/v1/subscriptions/create-order", json={"tier": "pro"})
        assert resp.status_code == 503
        [line] = [r for r in caplog.records if "Razorpay is not configured" in r.getMessage()]
        assert line.levelname == "ERROR"


class TestVerifyPaymentIsBoundToTheOrder:
    """GB083: the signature covers order_id|payment_id only, so the tier and the
    business have to be checked against the order itself."""

    def _verify(self, auth_client, order, tier, payment_id="pay_bound"):
        with patch.object(razorpay_client, "verify_payment_signature", return_value=True), \
                patch.object(razorpay_client, "fetch_order", return_value=order):
            return auth_client.post(
                "/api/v1/subscriptions/verify-payment",
                json={
                    "razorpay_order_id": "order_x",
                    "razorpay_payment_id": payment_id,
                    "razorpay_signature": "valid_sig",
                    "tier": tier,
                },
            )

    def test_paying_for_one_tier_and_claiming_another_is_refused(
        self, auth_client, db_session, business
    ):
        cheapest_paid = min(
            (t for t in SubscriptionTier if t != SubscriptionTier.FREE),
            key=lambda t: razorpay_client.TIER_PRICING[t]["price_monthly"],
        )
        resp = self._verify(
            auth_client, _paid_order(business.id, cheapest_paid.value), "enterprise"
        )
        assert resp.status_code == 400
        assert usage_service.get_tier(db_session, business.id) != SubscriptionTier.ENTERPRISE

    def test_another_businesss_paid_order_is_refused(self, auth_client, db_session, business):
        resp = self._verify(auth_client, _paid_order(business.id + 999, "pro"), "pro")
        assert resp.status_code == 400

    def test_an_order_that_is_not_paid_is_refused(self, auth_client, business):
        order = {**_paid_order(business.id, "pro"), "status": "attempted", "amount_paid": 0}
        assert self._verify(auth_client, order, "pro").status_code == 400

    def test_an_order_that_cannot_be_read_is_not_granted(self, auth_client, business):
        assert self._verify(auth_client, None, "pro").status_code == 502

    def test_a_payment_redeemed_by_another_business_is_refused(
        self, auth_client, db_session, business
    ):
        from app.models.business import Business, BusinessPlan

        other = Business(legal_name="Elsewhere Pvt Ltd", plan=BusinessPlan.FREE, is_active=True)
        db_session.add(other)
        db_session.flush()
        db_session.add(
            Subscription(
                business_id=other.id,
                tier=SubscriptionTier.PRO,
                status=SubscriptionStatus.ACTIVE,
                razorpay_subscription_id="pay_shared",
            )
        )
        db_session.commit()
        resp = self._verify(
            auth_client, _paid_order(business.id, "pro"), "pro", payment_id="pay_shared"
        )
        assert resp.status_code == 409

    def test_a_matching_paid_order_still_activates(self, auth_client, business):
        resp = self._verify(auth_client, _paid_order(business.id, "pro"), "pro")
        assert resp.status_code == 200
        assert resp.json()["tier"] == "pro"


class TestASignedBodyOfTheWrongShapeIsNotA500:
    """Only the top level was checked for being an object. A signed body whose
    ``payload``, ``payment`` or ``entity`` was a list, a string or null — or
    whose id was not a string — raised in the lookup chain, and a 500 is what
    Razorpay retries for a day."""

    @pytest.mark.parametrize(
        "body",
        [
            b'{"event":"payment.failed","payload":[]}',
            b'{"event":"payment.failed","payload":"x"}',
            b'{"event":"payment.failed","payload":{"payment":[]}}',
            b'{"event":"payment.failed","payload":{"payment":null,"subscription":{"entity":"s"}}}',
            b'{"event":"payment.failed","payload":{"subscription":"x"}}',
            b'{"event":"payment.failed","payload":{"payment":{"entity":{"id":{"a":1}}}}}',
            b'{"event":["x"],"payload":{"payment":{"entity":{"id":"pay_1"}}}}',
        ],
    )
    def test_it_is_acknowledged_and_changes_nothing(self, client, body):
        with patch.object(razorpay_client, "verify_webhook_signature", return_value=True):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=body,
                headers={"X-Razorpay-Signature": "good"},
            )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_a_body_nested_past_the_recursion_limit_is_not_json(self, client):
        with patch.object(razorpay_client, "verify_webhook_signature", return_value=True):
            response = client.post(
                "/api/v1/subscriptions/webhook",
                content=b"[" * 50_000 + b"]" * 50_000,
                headers={"X-Razorpay-Signature": "good"},
            )
        assert response.status_code == 400
