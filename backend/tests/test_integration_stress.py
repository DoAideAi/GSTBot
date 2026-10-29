"""M5 integration-point stress tests: what happens when external services
misbehave, and whether the product degrades rather than crashes.

Covers:
1. Razorpay client — malformed bodies, timeouts, non-ASCII signatures.
2. OpenRouter client — retry budget exhaustion, wrong-shape completions.
3. Email sender — transient classification, address redaction.
4. Invoice parser — model failure falls back to heuristics end-to-end.
5. Alert delivery — one tenant's failure does not block the rest.
"""
from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.services import razorpay_client
from app.services.email_sender import (
    EmailSendError,
    _is_transient,
    _transient_code,
    _without_addresses,
    send_email,
)
from app.services.openrouter_client import (
    OpenRouterError,
    _completion_text,
    _retry_after_seconds,
    extract_json_object,
)

# -----------------------------------------------------------------------
# 1. Razorpay: malformed bodies and edge cases
# -----------------------------------------------------------------------

class TestRazorpayObjectValidation:
    """``_object()`` must reject bodies that are not the expected shape."""

    def test_a_list_is_not_an_order(self):
        resp = httpx.Response(200, json=[1, 2, 3])
        with pytest.raises(ValueError, match="expected a JSON object"):
            razorpay_client._object(resp, "id")

    def test_a_string_is_not_an_order(self):
        resp = httpx.Response(200, json="ok")
        with pytest.raises(ValueError, match="expected a JSON object"):
            razorpay_client._object(resp, "id")

    def test_null_is_not_an_order(self):
        resp = httpx.Response(200, content=b"null")
        with pytest.raises((ValueError, Exception)):
            razorpay_client._object(resp, "id")

    def test_a_number_is_not_an_order(self):
        resp = httpx.Response(200, json=42)
        with pytest.raises(ValueError, match="expected a JSON object"):
            razorpay_client._object(resp, "id")

    def test_missing_required_keys_are_named(self):
        resp = httpx.Response(200, json={"status": "created"})
        with pytest.raises(ValueError, match="id"):
            razorpay_client._object(resp, "id", "amount")

    def test_a_complete_object_passes(self):
        resp = httpx.Response(
            200, json={"id": "order_1", "amount": 9900, "currency": "INR"},
        )
        obj = razorpay_client._object(resp, "id", "amount")
        assert obj["id"] == "order_1"


class TestRazorpaySignatureEdgeCases:
    """The constant-time compare must not raise on non-ASCII or empty input."""

    def test_a_non_ascii_signature_is_simply_wrong(self):
        assert razorpay_client._same("abc123", "abc12é") is False

    def test_an_empty_signature_is_wrong(self):
        assert razorpay_client._same("abc123", "") is False

    def test_identical_strings_match(self):
        assert razorpay_client._same("abc", "abc") is True

    def test_unicode_signature_both_sides(self):
        assert razorpay_client._same("señor", "señor") is True


class TestRazorpayDegradationWhenUnconfigured:

    def test_create_order_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_id", "")
        assert razorpay_client.create_order(9900) is None

    def test_cancel_subscription_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_id", "")
        assert razorpay_client.cancel_subscription("sub_1") is None

    def test_fetch_order_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_id", "")
        assert razorpay_client.fetch_order("order_1") is None


class TestRazorpayNetworkFailures:

    @pytest.fixture(autouse=True)
    def _configured(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test")
        monkeypatch.setattr(settings, "razorpay_key_secret", "secret")

    def test_create_order_survives_a_timeout(self):
        with patch.object(httpx, "post", side_effect=httpx.ReadTimeout("timeout")):
            assert razorpay_client.create_order(9900) is None

    def test_create_order_survives_a_connection_error(self):
        with patch.object(httpx, "post", side_effect=httpx.ConnectError("refused")):
            assert razorpay_client.create_order(9900) is None

    @pytest.mark.parametrize(
        "body",
        [
            {"id": 5, "amount": 9900, "currency": "INR"},  # id not a string
            {"id": "order_1", "amount": "9900", "currency": "INR"},  # amount a string
            {"id": "order_1", "amount": 9900, "currency": None},
            {"id": "order_" + "a" * 100, "amount": 9900, "currency": "INR"},  # too long
            {"id": "order/../payments", "amount": 9900, "currency": "INR"},
        ],
    )
    def test_create_order_refuses_an_order_checkout_could_not_complete(self, body):
        """P23 M5: the keys were checked, not their contents. A wrong type was
        a 500 from the route's response model; an id unlike Razorpay's went to
        the browser, was paid, and was then refused by verify-payment."""
        resp = httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx, "post", return_value=resp):
            assert razorpay_client.create_order(9900) is None

    def test_a_well_formed_order_still_comes_back(self):
        body = {"id": "order_Ab12_cd", "amount": 9900, "currency": "INR"}
        resp = httpx.Response(200, json=body, request=httpx.Request("POST", "https://x"))
        with patch.object(httpx, "post", return_value=resp):
            assert razorpay_client.create_order(9900) == body

    def test_fetch_order_survives_a_500(self):
        resp = httpx.Response(500, request=httpx.Request("GET", "https://x"))
        with patch.object(httpx, "get", return_value=resp):
            assert razorpay_client.fetch_order("order_1") is None

    def test_cancel_subscription_survives_a_timeout(self):
        with patch.object(httpx, "post", side_effect=httpx.ReadTimeout("timeout")):
            assert razorpay_client.cancel_subscription("sub_1") is None


# -----------------------------------------------------------------------
# 2. OpenRouter: wrong-shape completions and retry budget
# -----------------------------------------------------------------------

class TestOpenRouterCompletionTextShapeGuards:
    """``_completion_text`` must raise OpenRouterError, never TypeError."""

    def test_a_non_json_body_is_caught(self):
        resp = MagicMock()
        resp.json.side_effect = ValueError("not json")
        with pytest.raises(OpenRouterError, match="non-JSON"):
            _completion_text(resp)

    def test_a_body_that_is_a_list_is_caught(self):
        resp = MagicMock()
        resp.json.return_value = [{"choices": []}]
        with pytest.raises(OpenRouterError, match="non-object"):
            _completion_text(resp)

    def test_a_body_with_no_choices_is_caught(self):
        resp = MagicMock()
        resp.json.return_value = {"id": "x"}
        with pytest.raises(OpenRouterError, match="no choices"):
            _completion_text(resp)

    def test_an_empty_choices_list_is_caught(self):
        resp = MagicMock()
        resp.json.return_value = {"choices": []}
        with pytest.raises(OpenRouterError, match="no choices"):
            _completion_text(resp)

    def test_a_choice_with_empty_content_is_caught(self):
        resp = MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "", "reasoning": ""}}],
        }
        with pytest.raises(OpenRouterError, match="empty completion"):
            _completion_text(resp)


class TestRetryAfterParsing:

    def test_a_plain_number_is_read(self):
        resp = MagicMock()
        resp.headers = {"retry-after": "5"}
        assert _retry_after_seconds(resp) == 5.0

    def test_a_negative_result_is_clamped_to_zero(self):
        resp = MagicMock()
        resp.headers = {"retry-after": "-3"}
        assert _retry_after_seconds(resp) == 0.0

    def test_missing_header_returns_none(self):
        resp = MagicMock()
        resp.headers = {}
        assert _retry_after_seconds(resp) is None

    def test_garbage_returns_none(self):
        resp = MagicMock()
        resp.headers = {"retry-after": "not-a-number-or-date"}
        assert _retry_after_seconds(resp) is None

    def test_no_headers_attribute_returns_none(self):
        assert _retry_after_seconds(None) is None


class TestExtractJsonFromMessyOutput:

    def test_a_json_object_in_prose_is_found(self):
        raw = 'Here is the result: {"gstin": "07AAACN0001A1Z5"} hope that helps'
        result = extract_json_object(raw)
        assert result["gstin"] == "07AAACN0001A1Z5"

    def test_a_triple_fenced_json_is_unwrapped(self):
        raw = '```json\n{"amount": 1000}\n```'
        result = extract_json_object(raw)
        assert result["amount"] == 1000

    def test_no_braces_returns_none(self):
        assert extract_json_object("just some text") is None

    def test_empty_string_returns_none(self):
        assert extract_json_object("") is None

    def test_a_bare_array_is_rejected(self):
        assert extract_json_object("[1, 2, 3]") is None


# -----------------------------------------------------------------------
# 3. Email sender: transient classification
# -----------------------------------------------------------------------

class TestSmtpTransientClassification:
    """4xx is SMTP's transient class; 5xx is permanent. Getting that backwards
    retries a bad password or a dead mailbox, which is how relays lock accounts."""

    def test_a_4xx_is_transient(self):
        assert _transient_code(450) is True

    def test_a_5xx_is_permanent(self):
        assert _transient_code(550) is False

    def test_a_3xx_is_permanent(self):
        assert _transient_code(354) is False

    def test_none_is_permanent(self):
        assert _transient_code(None) is False

    def test_a_string_is_permanent(self):
        assert _transient_code("450") is True

    def test_garbage_is_permanent(self):
        assert _transient_code("banana") is False

    def test_server_disconnected_is_transient(self):
        assert _is_transient(smtplib.SMTPServerDisconnected("gone")) is True

    def test_a_permanent_smtp_error_is_not_transient(self):
        exc = smtplib.SMTPResponseException(550, b"no such user")
        assert _is_transient(exc) is False

    def test_a_transient_smtp_error_is_transient(self):
        exc = smtplib.SMTPResponseException(450, b"try again")
        assert _is_transient(exc) is True

    def test_authentication_failure_is_permanent(self):
        exc = smtplib.SMTPAuthenticationError(535, b"bad password")
        assert _is_transient(exc) is False

    def test_connection_refused_is_transient(self):
        assert _is_transient(ConnectionRefusedError("refused")) is True

    def test_dns_failure_is_transient(self):
        assert _is_transient(OSError("Name resolution failed")) is True

    def test_a_bare_smtp_exception_is_not_transient(self):
        assert _is_transient(smtplib.SMTPException("generic")) is False

    def test_recipients_all_deferred_is_transient(self):
        exc = smtplib.SMTPRecipientsRefused(
            {"a@x.com": (450, b"deferred"), "b@x.com": (451, b"busy")},
        )
        assert _is_transient(exc) is True

    def test_one_permanent_recipient_among_deferred_is_not_transient(self):
        exc = smtplib.SMTPRecipientsRefused(
            {"a@x.com": (450, b"deferred"), "b@x.com": (550, b"no such user")},
        )
        assert _is_transient(exc) is False

    def test_empty_recipients_is_not_transient(self):
        exc = smtplib.SMTPRecipientsRefused({})
        assert _is_transient(exc) is False


class TestAddressRedaction:
    """Error messages must not log recipient addresses."""

    def test_an_address_in_the_error_is_replaced(self):
        exc = Exception("450 4.7.1 user@example.com: Recipient address rejected")
        assert "user@example.com" not in _without_addresses(exc)
        assert "[address]" in _without_addresses(exc)

    def test_multiple_addresses_are_all_replaced(self):
        exc = Exception("foo@bar.com rejected; cc@dd.com deferred")
        text = _without_addresses(exc)
        assert "foo@bar.com" not in text
        assert "cc@dd.com" not in text

    def test_no_address_means_nothing_changed(self):
        exc = Exception("Connection refused")
        assert _without_addresses(exc) == "Connection refused"


class TestEmailSendErrorOnPermanentFailure:

    def test_a_permanent_5xx_is_not_retried(self, monkeypatch):
        monkeypatch.setattr(settings, "smtp_max_attempts", 3)
        call_count = 0

        def fail_permanently(*_a, **_k):
            nonlocal call_count
            call_count += 1
            raise smtplib.SMTPResponseException(550, b"no such user")

        monkeypatch.setattr("app.services.email_sender._deliver", fail_permanently)
        with pytest.raises(EmailSendError, match="1 attempt"):
            send_email(to="x@y.com", subject="test", body="hi")
        assert call_count == 1


# -----------------------------------------------------------------------
# 4. Invoice parser: model failure → heuristic fallback
# -----------------------------------------------------------------------

class TestInvoiceParserFallsBackWhenModelFails:

    def test_a_text_invoice_is_parsed_by_heuristics_when_the_model_is_absent(self):
        from app.services.invoice_parser import parse_invoice

        text = (
            "Invoice No: INV-2026-001\n"
            "Date: 15/04/2026\n"
            "GSTIN: 07AAACN0001A1Z5\n"
            "Taxable Value: 10000.00\n"
            "CGST @ 9%: 900.00\n"
            "SGST @ 9%: 900.00\n"
            "Total: 11800.00\n"
        )
        result = parse_invoice(text=text)
        assert result.invoice_number == "INV-2026-001"
        assert result.parsed_with == "heuristic"

    def test_a_model_failure_still_extracts_the_invoice_number(self):
        from app.services.invoice_parser import parse_invoice

        text = (
            "Invoice No: GST/001\n"
            "Date: 01/05/2026\n"
            "Total: 5000.00\n"
            "IGST @ 18%: 900.00\n"
        )
        result = parse_invoice(text=text)
        assert result.invoice_number == "GST/001"
        assert result.parsed_with == "heuristic"


class TestInvoiceUploadSurvivesModelFailure:

    def test_upload_returns_201_even_without_ai(self, auth_client):
        import io

        text = (
            "Invoice No: FALL-001\n"
            "Date: 01/05/2026\n"
            "GSTIN: 07AAACN0001A1Z5\n"
            "Taxable Value: 1000.00\n"
            "IGST @ 18%: 180.00\n"
            "Total: 1180.00\n"
        )
        resp = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("invoice.txt", io.BytesIO(text.encode()), "text/plain")},
        )
        assert resp.status_code == 201
        body = resp.json()
        inv = body.get("invoice", body)
        assert inv["parsed_with"] == "heuristic"


# -----------------------------------------------------------------------
# 5. Alert delivery: one tenant failure does not block the rest
# -----------------------------------------------------------------------

class TestAlertDeliveryIsolation:
    """A bad address or SMTP failure on one tenant must not end the run."""

    def test_send_pending_alerts_degrades_when_email_is_off(self, db_session):
        from app.services.alert_delivery import AlertEmailResult, send_pending_alerts

        result = send_pending_alerts(db_session)
        assert isinstance(result, AlertEmailResult)
        assert result.businesses == 0

    def test_send_to_all_counts_partial_success(self):
        from app.services.alert_delivery import _send_to_all

        call_count = 0

        def flaky_send(*, to, subject, body):
            nonlocal call_count
            call_count += 1
            if "bad" in to:
                raise EmailSendError("relay refused")

        with patch("app.services.alert_delivery.send_email", flaky_send):
            reached = _send_to_all(
                ["good@example.com", "bad@example.com"],
                "subject",
                "body",
                business_id=1,
            )
        assert reached is True
        assert call_count == 2

    def test_send_to_all_returns_false_when_all_fail(self):
        from app.services.alert_delivery import _send_to_all

        def always_fail(*, to, subject, body):
            raise EmailSendError("all bad")

        with patch("app.services.alert_delivery.send_email", always_fail):
            reached = _send_to_all(
                ["a@x.com", "b@x.com"],
                "subject",
                "body",
                business_id=1,
            )
        assert reached is False


# -----------------------------------------------------------------------
# 6. Razorpay webhook signature verification
# -----------------------------------------------------------------------

class TestWebhookSignatureVerification:

    def test_missing_secret_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_webhook_secret", "")
        assert razorpay_client.verify_webhook_signature(b"body", "sig") is False

    def test_wrong_signature_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_webhook_secret", "secret")
        assert razorpay_client.verify_webhook_signature(b"body", "wrong") is False

    def test_correct_signature_accepts(self, monkeypatch):
        import hashlib
        import hmac

        monkeypatch.setattr(settings, "razorpay_webhook_secret", "testsecret")
        body = b'{"event":"payment.captured"}'
        expected = hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
        assert razorpay_client.verify_webhook_signature(body, expected) is True

    def test_non_ascii_signature_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_webhook_secret", "secret")
        assert razorpay_client.verify_webhook_signature(b"body", "café") is False


class TestPaymentSignatureVerification:

    def test_missing_secret_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_secret", "")
        assert razorpay_client.verify_payment_signature("o1", "p1", "sig") is False

    def test_correct_signature_accepts(self, monkeypatch):
        import hashlib
        import hmac

        monkeypatch.setattr(settings, "razorpay_key_secret", "testsecret")
        message = "order_1|pay_1"
        expected = hmac.new(b"testsecret", message.encode(), hashlib.sha256).hexdigest()
        assert razorpay_client.verify_payment_signature("order_1", "pay_1", expected) is True

    def test_wrong_signature_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_key_secret", "testsecret")
        assert razorpay_client.verify_payment_signature("o1", "p1", "wrong") is False
