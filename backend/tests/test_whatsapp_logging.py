"""The WhatsApp webhook must never log a raw phone number."""
from __future__ import annotations

import hashlib
import logging
from unittest.mock import patch

import pytest


class TestInvalidSignatureLogging:
    """When Twilio signature verification fails, the sender's phone must be hashed."""

    @pytest.fixture(autouse=True)
    def _enable_twilio_auth(self):
        with patch("app.routers.whatsapp.settings") as mock_settings:
            mock_settings.whatsapp_twilio_auth_token = "test-token"
            mock_settings.whatsapp_webhook_base_url = ""
            mock_settings.whatsapp_verify_token = ""
            yield

    def _post_invalid_sig(self, client, phone="+919876543210"):
        client.post(
            "/api/v1/whatsapp/webhook",
            data={"From": phone, "Body": "hello"},
            headers={
                "X-Twilio-Signature": "bad-sig",
                "content-type": "application/x-www-form-urlencoded",
            },
        )

    def test_raw_phone_never_appears_in_log(self, client, caplog):
        phone = "+919876543210"
        with caplog.at_level(logging.WARNING, logger="app.routers.whatsapp"):
            self._post_invalid_sig(client, phone)
        for record in caplog.records:
            assert phone not in record.getMessage()
            assert phone != getattr(record, "sender_hash", "")

    def test_sender_hash_appears_in_log(self, client, caplog):
        phone = "+919876543210"
        expected_hash = hashlib.sha256(phone.encode()).hexdigest()[:12]
        with caplog.at_level(logging.WARNING, logger="app.routers.whatsapp"):
            self._post_invalid_sig(client, phone)
        sig_records = [r for r in caplog.records if r.name == "app.routers.whatsapp"]
        assert any(getattr(r, "sender_hash", "") == expected_hash for r in sig_records)

    def test_returns_403_on_invalid_signature(self, client):
        response = client.post(
            "/api/v1/whatsapp/webhook",
            data={"From": "+911234567890", "Body": "test"},
            headers={"X-Twilio-Signature": "bad-sig", "content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 403
