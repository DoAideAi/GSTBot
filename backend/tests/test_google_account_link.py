"""Linking must prove both accounts and preserve the existing tenant."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.security import hash_password
from app.models.business import Business
from app.models.user import User
from app.routers import oauth
from app.services import google_account_link as linking
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

LINK = "/api/v1/auth/google/link"
CALLBACK = "/api/v1/auth/google/callback"


@pytest.fixture
def flow(auth_client, db_session, monkeypatch):
    auth_client.headers.pop("Authorization")
    user = db_session.scalar(select(User).where(User.email == TEST_EMAIL))
    info = {"sub": "google-subject-123", "email": TEST_EMAIL.upper(), "email_verified": True}
    google = SimpleNamespace(authorize_access_token=AsyncMock(return_value={"userinfo": info}))
    monkeypatch.setattr(settings, "google_client_id", "gst-client")
    monkeypatch.setattr(oauth, "_configured_client", lambda provider: google)
    return SimpleNamespace(client=auth_client, user=user, info=info, google=google, db=db_session)


def start(flow):
    response = flow.client.get(CALLBACK, follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/auth/link-google")
    assert "token=" not in response.headers["location"]
    status = flow.client.get(LINK)
    assert status.status_code == 200, status.text
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["email"] == TEST_EMAIL
    return {"password": TEST_PASSWORD, "csrf_token": status.json()["csrf_token"]}


def test_google_and_password_link_the_same_account_without_replacing_its_data(flow):
    original = (flow.user.id, flow.user.business_id, flow.user.hashed_password, flow.user.role)
    business = flow.db.get(Business, flow.user.business_id)
    business_name = business.legal_name
    body = start(flow)
    assert flow.user.oauth_provider is None
    assert flow.client.get("/api/v1/auth/me").status_code == 401
    response = flow.client.post(LINK, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    flow.db.refresh(flow.user)
    assert (
        flow.user.id, flow.user.business_id, flow.user.hashed_password, flow.user.role
    ) == original
    assert flow.user.oauth_provider == "google"
    assert flow.user.oauth_id == flow.info["sub"]
    assert flow.db.get(Business, flow.user.business_id).legal_name == business_name
    token = response.json()["access_token"]
    me = flow.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert flow.client.post("/api/v1/auth/login", data={
        "username": TEST_EMAIL, "password": TEST_PASSWORD,
    }).status_code == 200
    # The second Google sign-in needs no password, and creates no new account.
    again = flow.client.get(CALLBACK, follow_redirects=False)
    assert urlsplit(again.headers["location"]).path == "/auth/callback"
    assert parse_qs(urlsplit(again.headers["location"]).fragment)["token"]
    assert len(flow.db.scalars(select(User)).all()) == 1
    assert len(flow.db.scalars(select(Business)).all()) == 1


def test_a_wrong_password_does_not_link_but_can_be_retried(flow):
    body = start(flow)
    refused = flow.client.post(LINK, json={**body, "password": "wrong-password"})
    assert refused.status_code == 400
    assert "Incorrect DoAide GST password" in refused.json()["detail"]
    flow.db.refresh(flow.user)
    assert flow.user.oauth_provider is None
    assert flow.client.post(LINK, json=body).status_code == 200


@pytest.mark.parametrize("csrf", ["wrong-token", "अन्य-token"])
def test_the_password_cannot_link_from_a_forged_cross_site_request(flow, csrf):
    body = start(flow)
    assert flow.client.post(LINK, json={**body, "csrf_token": csrf}).status_code == 403
    flow.db.refresh(flow.user)
    assert flow.user.oauth_id is None


def test_a_password_without_google_proof_is_insufficient(flow):
    assert flow.client.get(LINK).status_code == 400
    assert flow.client.post(LINK, json={
        "password": TEST_PASSWORD, "csrf_token": "forged",
    }).status_code == 400


def test_a_copied_cookie_cannot_replay_a_completed_link(flow):
    body = start(flow)
    cookie = flow.client.cookies.get("session")
    assert flow.client.post(LINK, json=body).status_code == 200
    flow.client.cookies.clear()
    flow.client.cookies.set("session", cookie)
    assert flow.client.post(LINK, json=body).status_code == 400


def test_a_tampered_session_cannot_supply_google_proof(flow):
    body = start(flow)
    cookie = flow.client.cookies.get("session")
    flow.client.cookies.clear()
    flow.client.cookies.set("session", "x" + cookie[1:])
    assert flow.client.post(LINK, json=body).status_code == 400


def test_the_google_proof_expires_after_five_minutes(flow, monkeypatch):
    body = start(flow)
    later = linking.time.time() + linking.LINK_SECONDS + 1
    monkeypatch.setattr(linking.time, "time", lambda: later)
    assert flow.client.post(LINK, json=body).status_code == 400


@pytest.mark.parametrize("change", [
    "password", "inactive", "email", "provider", "client", "deleted",
])
def test_a_link_is_invalidated_when_the_account_or_client_changes(flow, monkeypatch, change):
    body = start(flow)
    if change == "password":
        flow.user.hashed_password = hash_password("changed-password")
    elif change == "inactive":
        flow.user.is_active = False
    elif change == "email":
        flow.user.email = "changed@example.com"
    elif change == "provider":
        flow.user.oauth_provider, flow.user.oauth_id = "github", "existing-github"
    elif change == "client":
        monkeypatch.setattr(settings, "google_client_id", "another-client")
    else:
        flow.db.delete(flow.user)
    flow.db.commit()
    assert flow.client.post(LINK, json=body).status_code == 400


@pytest.mark.parametrize("verified", [False, None, "true"])
def test_an_unverified_google_email_never_starts_linking(flow, verified):
    flow.info["email_verified"] = verified
    response = flow.client.get(CALLBACK, follow_redirects=False)
    assert "/auth/link-google" not in response.headers["location"]
    assert flow.client.get(LINK).status_code == 400


def test_a_deactivated_account_is_not_offered_linking(flow):
    flow.user.is_active = False
    flow.db.commit()
    response = flow.client.get(CALLBACK, follow_redirects=False)
    assert response.headers["location"].endswith("error=account_deactivated")
    assert flow.client.get(LINK).status_code == 400


def test_an_existing_provider_is_never_overwritten(flow):
    flow.user.oauth_provider, flow.user.oauth_id = "microsoft", "existing-subject"
    flow.db.commit()
    response = flow.client.get(CALLBACK, follow_redirects=False)
    assert response.headers["location"].endswith("error=account_link_required")
    assert flow.client.get(LINK).status_code == 400


def test_a_competing_google_identity_is_refused_without_losing_the_password(flow):
    body = start(flow)
    flow.db.add(User(email="other@example.com", business_id=flow.user.business_id,
                     oauth_provider="google", oauth_id=flow.info["sub"]))
    flow.db.commit()
    assert flow.client.post(LINK, json=body).status_code == 400
    flow.db.refresh(flow.user)
    assert flow.user.oauth_provider is None


def test_a_concurrent_password_reset_wins_over_linking(flow, monkeypatch):
    body = start(flow)
    original_verify = linking.verify_password

    def reset_while_verifying(password, hashed):
        flow.db.execute(update(User).where(User.id == flow.user.id).values(
            hashed_password=hash_password("reset-during-link")),
            execution_options={"synchronize_session": False})
        flow.db.commit()
        return original_verify(password, hashed)

    monkeypatch.setattr(linking, "verify_password", reset_while_verifying)
    assert flow.client.post(LINK, json=body).status_code == 400
    flow.db.refresh(flow.user)
    assert flow.user.oauth_id is None


def test_new_google_attempts_and_network_addresses_share_the_account_budget(
    flow, rate_limited, pinned_window, monkeypatch,
):
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    for index in range(11):
        # Per-IP buckets remain independent; the account's budget must not.
        flow.client.headers["X-Forwarded-For"] = f"198.51.100.{index + 1}"
        body = start(flow)
        response = flow.client.post(LINK, json={**body, "password": "wrong"})
        assert response.status_code == (400 if index < 10 else 429), response.text
    assert "Retry-After" in response.headers
    assert "Too many password attempts" in response.json()["detail"]
