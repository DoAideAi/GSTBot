"""Tests for the bulk GSTIN validation endpoint and the require_paid_tier gate."""
from __future__ import annotations

from sqlalchemy import select

from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier

VALID_GSTIN = "27AAPFU0939F1ZV"
VALID_GSTIN_2 = "29AAPFU0939F1ZT"
INVALID_GSTIN = "27AAPFU0939F1ZX"
GARBAGE = "not-a-gstin"


def _activate_pro(db_session, business_id: int) -> None:
    """Give the business a paid subscription."""
    sub = db_session.scalar(
        select(Subscription).where(Subscription.business_id == business_id)
    )
    if sub is None:
        sub = Subscription(
            business_id=business_id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
    else:
        sub.tier = SubscriptionTier.PRO
        sub.status = SubscriptionStatus.ACTIVE
    db_session.commit()


class TestBulkGstinRequiresPaidTier:
    def test_a_free_user_is_refused(self, auth_client, business):
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        assert resp.status_code == 403
        assert "paid subscription" in resp.json()["detail"].lower()

    def test_an_unauthenticated_caller_gets_401(self, client):
        resp = client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        assert resp.status_code == 401


class TestBulkGstinValidation:
    def test_a_single_valid_gstin(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["valid_count"] == 1
        assert data["invalid_count"] == 0
        assert data["results"][0]["valid"] is True
        assert data["results"][0]["gstin"] == VALID_GSTIN

    def test_mixed_valid_and_invalid(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN, INVALID_GSTIN, GARBAGE]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["valid_count"] == 1
        assert data["invalid_count"] == 2
        assert data["results"][0]["valid"] is True
        assert data["results"][1]["valid"] is False
        assert data["results"][1]["error"] is not None
        assert data["results"][2]["valid"] is False

    def test_empty_list_is_rejected(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": []},
        )
        assert resp.status_code == 422

    def test_over_100_gstins_is_rejected(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN] * 101},
        )
        assert resp.status_code == 422

    def test_exactly_100_gstins_is_accepted(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN] * 100},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 100

    def test_valid_gstin_returns_state_and_pan(self, auth_client, business, db_session):
        _activate_pro(db_session, business.id)
        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        result = resp.json()["results"][0]
        assert result["state_code"] == "27"
        assert result["state_name"] == "Maharashtra"
        assert result["pan"] == "AAPFU0939F"

    def test_enterprise_tier_also_works(self, auth_client, business, db_session):
        sub = db_session.scalar(
            select(Subscription).where(Subscription.business_id == business.id)
        )
        if sub is None:
            sub = Subscription(
                business_id=business.id,
                tier=SubscriptionTier.ENTERPRISE,
                status=SubscriptionStatus.ACTIVE,
            )
            db_session.add(sub)
        else:
            sub.tier = SubscriptionTier.ENTERPRISE
            sub.status = SubscriptionStatus.ACTIVE
        db_session.commit()

        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        assert resp.status_code == 200

    def test_cancelled_subscription_is_refused(self, auth_client, business, db_session):
        sub = Subscription(
            business_id=business.id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.CANCELLED,
        )
        db_session.add(sub)
        db_session.commit()

        resp = auth_client.post(
            "/api/v1/meta/gstin/bulk",
            json={"gstins": [VALID_GSTIN]},
        )
        assert resp.status_code == 403
