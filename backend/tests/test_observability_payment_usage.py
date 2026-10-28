"""Observability on the payment and usage paths.

GB024 (M11 — observability), pass 5: Razorpay failure logs must carry structured
context (operation, status code, identifiers), and the usage module must log when
a business hits its tier limit so abuse and capacity patterns are visible in a
log aggregator.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.services import razorpay_client, usage

# ── Razorpay: structured context on failure lines ────────────────────────

class TestRazorpayFailureLogsCarryStructuredContext:
    """Every ``logger.exception`` in the Razorpay client must carry the
    operation name and the HTTP status code (when one was received) as
    ``extra`` fields, so an operator filtering for payment failures in a log
    aggregator can tell which call failed and why without parsing the message.
    """

    @pytest.fixture(autouse=True)
    def _configured(self, monkeypatch):
        monkeypatch.setattr(razorpay_client.settings, "razorpay_key_id", "rzp_test_key")
        monkeypatch.setattr(razorpay_client.settings, "razorpay_key_secret", "rzp_test_secret")

    def _http_error(self, status: int = 500) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", "https://api.razorpay.com/v1/test")
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError("server error", request=request, response=response)

    def test_create_order_failure_carries_amount(self, monkeypatch, caplog):
        monkeypatch.setattr(
            httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(self._http_error(500))
        )
        with caplog.at_level(logging.ERROR, logger="app.services.razorpay_client"):
            result = razorpay_client.create_order(499_00)

        assert result is None
        errors = [
            r for r in caplog.records
            if r.name == "app.services.razorpay_client" and r.levelno >= logging.ERROR
        ]
        assert errors
        assert errors[0].operation == "create_order"
        assert errors[0].amount_paise == 499_00

    def test_cancel_subscription_failure_carries_subscription_id(self, monkeypatch, caplog):
        monkeypatch.setattr(
            httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(self._http_error(404))
        )
        with caplog.at_level(logging.ERROR, logger="app.services.razorpay_client"):
            result = razorpay_client.cancel_subscription("sub_abc123")

        assert result is None
        errors = [
            r for r in caplog.records
            if r.name == "app.services.razorpay_client" and r.levelno >= logging.ERROR
        ]
        assert errors
        assert errors[0].operation == "cancel_subscription"
        assert errors[0].subscription_id == "sub_abc123"
        assert errors[0].status_code == 404

    def test_a_transport_error_carries_null_status(self, monkeypatch, caplog):
        """A connect timeout has no HTTP status to report."""
        monkeypatch.setattr(
            httpx, "post",
            lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("connection refused")),
        )
        with caplog.at_level(logging.ERROR, logger="app.services.razorpay_client"):
            razorpay_client.create_order(9900)

        errors = [
            r for r in caplog.records
            if r.name == "app.services.razorpay_client" and r.levelno >= logging.ERROR
        ]
        assert errors
        assert errors[0].operation == "create_order"
        assert errors[0].status_code is None


# ── Usage: limit enforcement is logged ───────────────────────────────────

class TestUsageLimitEnforcementIsLogged:
    """When a business hits its tier's usage limit, the refusal must be
    logged with enough context to filter by business, endpoint and tier in
    a log aggregator.
    """

    def test_a_limit_hit_is_logged_with_structured_fields(self, db_session, caplog):
        from app.models.business import Business

        business = Business(
            gstin="27AAPFU0939F1ZV", legal_name="Test Co",
            state_code="27",
        )
        db_session.add(business)
        db_session.commit()
        db_session.refresh(business)

        # Free tier allows 5 gst_lookups — exhaust them.
        for _ in range(5):
            usage.record_usage(db_session, business.id, "gst_lookup")
        db_session.commit()

        with caplog.at_level(logging.WARNING, logger="app.services.usage"):
            allowed, used, limit = usage.check_limit(db_session, business.id, "gst_lookup")

        assert not allowed
        assert used == 5
        assert limit == 5

        warnings = [
            r for r in caplog.records
            if r.name == "app.services.usage" and r.levelno >= logging.WARNING
        ]
        assert warnings, "No warning emitted when usage limit is reached"
        record = warnings[0]
        assert record.business_id == business.id
        assert record.endpoint == "gst_lookup"
        assert record.used == 5
        assert record.limit == 5
        assert record.tier == "free"

    def test_an_allowed_call_is_not_logged(self, db_session, caplog):
        from app.models.business import Business

        business = Business(
            gstin="27AAPFU0939F1ZV", legal_name="Test Co",
            state_code="27",
        )
        db_session.add(business)
        db_session.commit()
        db_session.refresh(business)

        with caplog.at_level(logging.WARNING, logger="app.services.usage"):
            allowed, _, _ = usage.check_limit(db_session, business.id, "gst_lookup")

        assert allowed
        warnings = [
            r for r in caplog.records
            if r.name == "app.services.usage" and r.levelno >= logging.WARNING
        ]
        assert not warnings, "No warning should be emitted when under the limit"

    def test_an_unlimited_endpoint_is_not_logged(self, db_session, caplog):
        from app.models.business import Business

        business = Business(
            gstin="27AAPFU0939F1ZV", legal_name="Test Co",
            state_code="27",
        )
        db_session.add(business)
        db_session.commit()
        db_session.refresh(business)

        with caplog.at_level(logging.WARNING, logger="app.services.usage"):
            allowed, _, limit = usage.check_limit(db_session, business.id, "hsn_search")

        assert allowed
        assert limit == 0
        warnings = [
            r for r in caplog.records
            if r.name == "app.services.usage" and r.levelno >= logging.WARNING
        ]
        assert not warnings
