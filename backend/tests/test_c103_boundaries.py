"""C103 Pass 14, M1: the edges of the paths Pass 13 changed.

The GSTIN lookup's 30-a-minute budget at exactly 30; bulk validation at its
size limits and with mixed input; and the paid-plan lifecycle around its
period end.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.services import razorpay_client
from app.services import usage as usage_service

GSTIN = "27AAPFU0939F1ZV"


class TestTheGstinLookupBudgetAtExactlyThirty:
    def test_the_thirtieth_lookup_is_served_and_the_thirty_first_refused(
        self, client, rate_limited, pinned_window
    ):
        responses = [client.get(f"/api/v1/meta/gstin/{GSTIN}") for _ in range(30)]
        assert [r.status_code for r in responses] == [200] * 30
        assert responses[-1].headers["X-RateLimit-Remaining"] == "0"

        refused = client.get(f"/api/v1/meta/gstin/{GSTIN}")
        assert refused.status_code == 429
        assert int(refused.headers["Retry-After"]) >= 1

    def test_the_next_window_gives_the_whole_budget_back(
        self, client, rate_limited, pinned_window
    ):
        for _ in range(31):
            client.get(f"/api/v1/meta/gstin/{GSTIN}")
        pinned_window(60)
        assert client.get(f"/api/v1/meta/gstin/{GSTIN}").status_code == 200


BULK = "/api/v1/meta/gstin/bulk"


class TestBulkGstinValidationAtItsEdges:
    def test_an_empty_list_is_refused_rather_than_answered_with_nothing(
        self, auth_client, paid_business
    ):
        assert auth_client.post(BULK, json={"gstins": []}).status_code == 422

    def test_exactly_a_hundred_is_accepted_and_a_hundred_and_one_is_not(
        self, auth_client, paid_business
    ):
        ok = auth_client.post(BULK, json={"gstins": [GSTIN] * 100})
        assert ok.status_code == 200
        assert ok.json()["total"] == 100
        assert auth_client.post(BULK, json={"gstins": [GSTIN] * 101}).status_code == 422

    def test_a_mix_is_answered_entry_by_entry_in_the_order_sent(
        self, auth_client, paid_business
    ):
        sent = [GSTIN, "27AAPFU0939F1ZW", "", " 27aapfu0939f1zv ", "00AAPFU0939F1ZV"]
        body = auth_client.post(BULK, json={"gstins": sent}).json()

        assert [r["valid"] for r in body["results"]] == [True, False, False, True, False]
        assert body["results"][3]["gstin"] == GSTIN  # normalised, not echoed raw
        assert (body["total"], body["valid_count"], body["invalid_count"]) == (5, 2, 3)
        assert all(r["error"] for r in body["results"] if not r["valid"])

    def test_an_entry_far_longer_than_any_gstin_is_refused(self, auth_client, paid_business):
        """Entries had no length bound and an invalid one is echoed back, so a
        request could make the server parse and return up to a hundred
        arbitrarily long strings. Bounded like the GPT lookup's path (64)."""
        assert auth_client.post(BULK, json={"gstins": ["X" * 65]}).status_code == 422
        assert auth_client.post(BULK, json={"gstins": ["X" * 64]}).status_code == 200

    def test_a_free_business_is_refused(self, auth_client, business):
        assert auth_client.post(BULK, json={"gstins": [GSTIN]}).status_code == 403


# ---------------------------------------------------------------------------
# The paid period
# ---------------------------------------------------------------------------

VERIFY = "/api/v1/subscriptions/verify-payment"


def _order(business_id: int, tier: str, billing: str = "monthly") -> dict:
    t = SubscriptionTier(tier)
    amount = razorpay_client.TIER_PRICING[t][f"price_{billing}"]
    return {
        "id": "order_x",
        "receipt": razorpay_client.order_receipt(business_id, t),
        "amount": amount,
        "amount_paid": amount,
        "status": "paid",
    }


def _pay(client, business_id, *, tier="pro", billing="monthly", payment="pay_1"):
    order = _order(business_id, tier, billing)
    with patch.object(
        razorpay_client, "verify_payment_signature", return_value=True
    ), patch.object(razorpay_client, "fetch_order", return_value=order):
        return client.post(
            VERIFY,
            json={
                "razorpay_order_id": "order_x",
                "razorpay_payment_id": payment,
                "razorpay_signature": "sig",
                "tier": tier,
            },
        )


def _end(response) -> datetime:
    return datetime.fromisoformat(response.json()["current_period_end"]).replace(tzinfo=UTC)


def _row(db_session, business_id) -> Subscription:
    db_session.expire_all()
    return db_session.query(Subscription).filter_by(business_id=business_id).one()


class TestOnePaymentBuysOnePeriod:
    """Checkout is a one-time order and nothing ended it: a single monthly
    payment kept a business on PRO forever."""

    @pytest.mark.parametrize(("billing", "days"), [("monthly", 30), ("annual", 365)])
    def test_the_period_is_set_from_what_was_paid(self, auth_client, business, billing, days):
        before = datetime.now(UTC)
        response = _pay(auth_client, business.id, billing=billing)
        assert response.status_code == 200
        end = _end(response)
        assert before + timedelta(days=days) <= end <= datetime.now(UTC) + timedelta(days=days)

    def test_a_lapsed_period_is_not_paid_for(self, auth_client, db_session, business):
        _pay(auth_client, business.id)
        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()

        assert auth_client.get("/api/v1/itc").status_code == 403
        assert usage_service.get_tier(db_session, business.id) == SubscriptionTier.FREE
        current = auth_client.get("/api/v1/subscriptions/current").json()
        assert current["status"] == "expired"

    def test_the_end_instant_itself_is_already_over(self):
        end = datetime(2026, 6, 1, tzinfo=UTC)
        sub = Subscription(
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
            current_period_end=end,
        )
        assert sub.is_paid(end - timedelta(seconds=1))
        assert not sub.is_paid(end)

    def test_paying_again_after_it_lapsed_starts_a_new_period_now(
        self, auth_client, db_session, business
    ):
        _pay(auth_client, business.id, payment="pay_1")
        sub = _row(db_session, business.id)
        sub.current_period_end = datetime.now(UTC) - timedelta(days=3)
        db_session.commit()

        before = datetime.now(UTC)
        renewed = _pay(auth_client, business.id, payment="pay_2")
        assert renewed.status_code == 200
        assert _end(renewed) >= before + timedelta(days=30)
        assert auth_client.get("/api/v1/itc").status_code == 200


class TestRenewingEarly:
    def test_a_same_tier_renewal_extends_from_the_current_end(
        self, auth_client, db_session, business
    ):
        first = _end(_pay(auth_client, business.id, payment="pay_1"))
        second = _end(_pay(auth_client, business.id, payment="pay_2"))
        assert second - first == timedelta(days=30)

    def test_replaying_the_same_payment_does_not_extend_it(self, auth_client, business):
        first = _end(_pay(auth_client, business.id, payment="pay_1"))
        again = _end(_pay(auth_client, business.id, payment="pay_1"))
        assert again == first

    def test_a_change_of_tier_starts_its_period_now(self, auth_client, business):
        _pay(auth_client, business.id, tier="pro", payment="pay_1")
        before = datetime.now(UTC)
        upgraded = _pay(auth_client, business.id, tier="enterprise", payment="pay_2")
        assert upgraded.json()["tier"] == "enterprise"
        end = _end(upgraded)
        assert before + timedelta(days=30) <= end <= datetime.now(UTC) + timedelta(days=30)


class TestARowWithNoEnd:
    def test_stays_paid_as_it_was_sold(self, auth_client, db_session, paid_business):
        """Rows from before the period existed, and grants made by hand."""
        assert _row(db_session, paid_business.id).current_period_end is None
        assert auth_client.get("/api/v1/itc").status_code == 200
        assert auth_client.get("/api/v1/subscriptions/current").json()["status"] == "active"
