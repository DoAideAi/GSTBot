"""GB033: tests for silent failure fixes.

Each test verifies that a code path which previously swallowed an error now
either logs it, surfaces it to the caller, or redirects with a user-visible
error code instead of silently succeeding or returning None.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services import razorpay_client

# ── OAuth: GitHub profile-fetch failure must redirect, not 500 ──


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_github_callback_profile_fetch_failure_redirects(client):
    """When token exchange succeeds but the GitHub user-profile API fails,
    the callback must redirect to the login page with an error — not crash
    with an unhandled 500."""
    from app.routers.oauth import oauth

    if not hasattr(oauth, "_clients") or "github" not in oauth._clients:
        oauth.register(
            name="github",
            client_id="test-id",
            client_secret="test-secret",
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "user:email"},
        )

    fake_token = {"access_token": "gho_test", "token_type": "bearer"}

    with (
        patch.object(settings, "github_client_id", "test-id"),
        patch.object(
            oauth.github, "authorize_access_token", new_callable=AsyncMock, return_value=fake_token
        ),
        patch.object(
            oauth.github, "get", new_callable=AsyncMock, side_effect=Exception("GitHub API down")
        ),
    ):
        resp = client.get("/api/v1/auth/github/callback", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert "error=github_auth_failed" in location


def test_github_callback_emails_fetch_failure_redirects(client):
    """When the primary profile has no email and the emails endpoint fails,
    the callback must redirect with an error."""
    from app.routers.oauth import oauth

    if not hasattr(oauth, "_clients") or "github" not in oauth._clients:
        oauth.register(
            name="github",
            client_id="test-id",
            client_secret="test-secret",
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "user:email"},
        )

    fake_token = {"access_token": "gho_test", "token_type": "bearer"}

    profile_resp = MagicMock()
    profile_resp.json.return_value = {"id": 12345, "login": "testuser", "email": None}

    call_count = 0

    async def _get_side_effect(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return profile_resp
        raise Exception("GitHub emails API down")

    with (
        patch.object(settings, "github_client_id", "test-id"),
        patch.object(
            oauth.github, "authorize_access_token", new_callable=AsyncMock, return_value=fake_token
        ),
        patch.object(oauth.github, "get", new_callable=AsyncMock, side_effect=_get_side_effect),
    ):
        resp = client.get("/api/v1/auth/github/callback", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers.get("location", "")
    assert "error=github_auth_failed" in location


# ── Razorpay: verify_payment_signature logs when secret is missing ──


def test_verify_payment_signature_logs_missing_secret(caplog):
    """When RAZORPAY_KEY_SECRET is empty, verify_payment_signature must
    log an error — not silently return False, which is indistinguishable
    from a forged signature."""
    with (
        patch.object(settings, "razorpay_key_secret", ""),
        caplog.at_level(logging.ERROR, logger="app.services.razorpay_client"),
    ):
        result = razorpay_client.verify_payment_signature("order_123", "pay_456", "sig_789")

    assert result is False
    assert any("not configured" in r.message for r in caplog.records)


def test_verify_webhook_signature_logs_missing_secret(caplog):
    """When RAZORPAY_WEBHOOK_SECRET is empty, verify_webhook_signature must
    log an error rather than silently rejecting."""
    with (
        patch.object(settings, "razorpay_webhook_secret", ""),
        caplog.at_level(logging.ERROR, logger="app.services.razorpay_client"),
    ):
        result = razorpay_client.verify_webhook_signature(b"body", "signature")

    assert result is False
    assert any("not configured" in r.message for r in caplog.records)


# ── Webhook: missing razorpay_id now logged ──


def test_webhook_missing_entity_id_is_logged(client, caplog):
    """A webhook payload with no identifiable entity must be logged as a
    warning so malformed payloads can be debugged."""
    payload = {
        "event": "payment.authorized",
        "payload": {"payment": {"entity": {}}},
    }
    with (
        patch.object(razorpay_client, "verify_webhook_signature", return_value=True),
        caplog.at_level(logging.WARNING, logger="app.routers.subscriptions"),
    ):
        resp = client.post(
            "/api/v1/subscriptions/webhook",
            json=payload,
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert any("no identifiable" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (b"{not json", "not valid JSON"),
        (b"\xff\xfe", "not valid JSON"),
        (b'["payment.captured"]', "must be a JSON object"),
        (b'"payment.captured"', "must be a JSON object"),
    ],
)
def test_a_signed_webhook_that_is_not_an_object_is_a_400_not_a_500(client, body, detail):
    """Razorpay retries a 5xx for a day; a body it can never fix should be refused once."""
    with patch.object(razorpay_client, "verify_webhook_signature", return_value=True):
        resp = client.post(
            "/api/v1/subscriptions/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 400
    assert detail in resp.text


# ── OpenRouter: _retry_after_seconds logs instead of bare pass ──


def test_retry_after_non_numeric_is_logged(caplog):
    """A Retry-After header that is neither a number nor a valid HTTP-date
    must produce a debug log instead of being swallowed silently."""
    from app.services.openrouter_client import _retry_after_seconds

    mock_resp = type("Response", (), {"headers": {"retry-after": "not-a-number-or-date"}})()

    with caplog.at_level(logging.DEBUG, logger="app.services.openrouter_client"):
        result = _retry_after_seconds(mock_resp)

    assert result is None
    assert any("not a plain number" in r.message for r in caplog.records)
