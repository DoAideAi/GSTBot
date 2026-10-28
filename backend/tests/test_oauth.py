"""Tests for OAuth SSO endpoints."""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.models.business import Business, BusinessPlan
from app.models.user import User, UserRole
from app.routers.oauth import _complete_oauth_login, _find_or_create_oauth_user, _provider_id


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_google_login_redirects_when_configured(client):
    from app.routers.oauth import oauth

    if not hasattr(oauth, "_clients") or "google" not in oauth._clients:
        oauth.register(
            name="google",
            client_id="test-id",
            client_secret="test-secret",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    with patch.object(settings, "google_client_id", "test-id"):
        resp = client.get("/api/v1/auth/google", follow_redirects=False)
        assert resp.status_code in (302, 307, 200)


def test_google_login_returns_501_when_not_configured(client):
    with patch.object(settings, "google_client_id", ""):
        resp = client.get("/api/v1/auth/google")
        assert resp.status_code == 501


def test_github_login_returns_501_when_not_configured(client):
    with patch.object(settings, "github_client_id", ""):
        resp = client.get("/api/v1/auth/github")
        assert resp.status_code == 501


def test_microsoft_login_returns_501_when_not_configured(client):
    with patch.object(settings, "microsoft_client_id", ""):
        resp = client.get("/api/v1/auth/microsoft")
        assert resp.status_code == 501


def test_google_callback_redirects_on_error(client):
    with patch.object(settings, "google_client_id", "test-id"):
        resp = client.get("/api/v1/auth/google/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "error" in location or "login" in location


def test_github_callback_redirects_on_error(client):
    with patch.object(settings, "github_client_id", "test-id"):
        resp = client.get("/api/v1/auth/github/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "error" in location or "login" in location


def test_microsoft_callback_redirects_on_error(client):
    with patch.object(settings, "microsoft_client_id", "test-id"):
        resp = client.get("/api/v1/auth/microsoft/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "error" in location or "login" in location


# ── GB020: is_active gate ──────────────────────────────────


def test_find_or_create_returns_none_for_inactive_user_by_oauth_id(db_session):
    """A deactivated user looked up by OAuth id must not receive a token."""
    business = Business(legal_name="Deactivated Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="deactivated@example.com",
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider="google",
        oauth_id="deactivated-gid",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    result = _find_or_create_oauth_user(
        db_session,
        provider="google",
        oauth_id="deactivated-gid",
        email="deactivated@example.com",
        name=None,
    )
    assert result is None


def test_find_or_create_returns_none_for_inactive_user_by_email(db_session):
    """A deactivated user looked up by email (no prior OAuth link) must not receive a token."""
    business = Business(legal_name="Suspended Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="suspended@example.com",
        hashed_password="unused",
        business_id=business.id,
        role=UserRole.OWNER,
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    result = _find_or_create_oauth_user(
        db_session,
        provider="github",
        oauth_id="new-github-id",
        email="suspended@example.com",
        name=None,
    )
    assert result is None
    # The OAuth link must NOT be written onto a deactivated account.
    db_session.refresh(user)
    assert user.oauth_provider is None


def test_find_or_create_returns_active_user(db_session):
    """An active user is returned normally."""
    business = Business(legal_name="Active Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="active@example.com",
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider="google",
        oauth_id="active-gid",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    result = _find_or_create_oauth_user(
        db_session,
        provider="google",
        oauth_id="active-gid",
        email="active@example.com",
        name=None,
    )
    assert result is not None
    assert result.id == user.id


# ── GB020: _complete_oauth_login redirects deactivated users ────


def test_complete_oauth_login_redirects_deactivated():
    """A None user (deactivated) must redirect to the login page with an error."""
    response = _complete_oauth_login(None, "google")
    assert response.status_code == 307
    assert "account_deactivated" in response.headers["location"]


# ── GB020: audit logging ────────────────────────────────────


def test_complete_oauth_login_logs_successful_login(db_session, caplog):
    """A successful OAuth login must produce an audit log line."""
    business = Business(legal_name="Logging Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="logged@example.com",
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider="google",
        oauth_id="log-gid",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.routers.oauth"):
        response = _complete_oauth_login(user, "google")

    assert response.status_code == 307
    assert "#token=" in response.headers["location"]
    assert any("OAuth login" in record.message for record in caplog.records)


def test_complete_oauth_login_does_not_log_for_deactivated(caplog):
    """No audit log for a deactivated user — there is no login to record."""
    with caplog.at_level(logging.INFO, logger="app.routers.oauth"):
        _complete_oauth_login(None, "github")

    assert not any("OAuth login" in record.message for record in caplog.records)


# ── GB020: rate limiting on callbacks ────────────────────────


def test_oauth_callback_routes_have_rate_limit_dependency():
    """Every OAuth callback route must declare a rate limit dependency."""
    from app.core.rate_limit import RateLimit
    from app.core.routes import collect_api_routes, dependency_calls
    from app.main import app as main_app

    callback_paths = [
        "/api/v1/auth/google/callback",
        "/api/v1/auth/github/callback",
        "/api/v1/auth/microsoft/callback",
    ]
    all_routes = collect_api_routes(main_app)
    for path in callback_paths:
        route = next(
            (r for r in all_routes if getattr(r, "path", None) == path),
            None,
        )
        assert route is not None, f"Route {path} not found"
        callables = list(dependency_calls(route.dependant))
        has_rate_limit = any(isinstance(c, RateLimit) for c in callables)
        assert has_rate_limit, f"{path} has no RateLimit dependency"


# ── GB027: token must not appear in query string ────────────


def test_oauth_token_uses_fragment_not_query_param(db_session):
    """The access token must be delivered in a URL fragment, not a query
    parameter. A query parameter is logged by proxies and servers and leaked
    via the Referer header; a fragment never leaves the browser."""
    business = Business(legal_name="Fragment Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="fragment@example.com",
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider="google",
        oauth_id="frag-gid",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    response = _complete_oauth_login(user, "google")
    location = response.headers["location"]
    assert "#token=" in location, "token must be in a URL fragment"
    assert "?token=" not in location, "token must NOT be in a query parameter"


# ── GB028: rate limiting on OAuth initiation ──────────────


def test_oauth_initiation_routes_have_rate_limit_dependency():
    """Every OAuth initiation route must declare a rate limit dependency."""
    from app.core.rate_limit import RateLimit
    from app.core.routes import collect_api_routes, dependency_calls
    from app.main import app as main_app

    initiation_paths = [
        "/api/v1/auth/google",
        "/api/v1/auth/github",
        "/api/v1/auth/microsoft",
    ]
    all_routes = collect_api_routes(main_app)
    for path in initiation_paths:
        route = next(
            (r for r in all_routes if getattr(r, "path", None) == path),
            None,
        )
        assert route is not None, f"Route {path} not found"
        callables = list(dependency_calls(route.dependant))
        has_rate_limit = any(isinstance(c, RateLimit) for c in callables)
        assert has_rate_limit, f"{path} has no RateLimit dependency"


# ── GB028: email_verified gate on account linking ─────────


def test_unverified_email_does_not_link_existing_account(db_session):
    """An OAuth provider that has NOT verified the email must not be allowed
    to link to an existing password-based account — doing so would let an
    attacker who controls an OAuth identity with a victim's unverified email
    take over that account."""
    business = Business(legal_name="Victim Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="victim@example.com",
        hashed_password="bcrypt-hash-here",
        business_id=business.id,
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    result = _find_or_create_oauth_user(
        db_session,
        provider="google",
        oauth_id="attacker-gid",
        email="victim@example.com",
        name="Attacker",
        email_verified=False,
    )
    assert result is None
    db_session.refresh(user)
    assert user.oauth_provider is None


def test_verified_email_links_existing_account(db_session):
    """When the OAuth provider HAS verified the email, linking to an existing
    password-based account is allowed."""
    business = Business(legal_name="Link Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="linkme@example.com",
        hashed_password="bcrypt-hash-here",
        business_id=business.id,
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    result = _find_or_create_oauth_user(
        db_session,
        provider="google",
        oauth_id="legit-gid",
        email="linkme@example.com",
        name="Legit",
        email_verified=True,
    )
    assert result is not None
    assert result.id == user.id
    assert result.oauth_provider == "google"
    assert result.oauth_id == "legit-gid"


def test_unverified_email_creates_new_account_if_no_match(db_session):
    """An unverified email that has no existing account should still create
    a new user — the gate only blocks linking to someone else's account."""
    result = _find_or_create_oauth_user(
        db_session,
        provider="github",
        oauth_id="brand-new-id",
        email="newuser@example.com",
        name="New User",
        email_verified=False,
    )
    assert result is not None
    assert result.email == "newuser@example.com"
    assert result.oauth_provider == "github"


# ── GB032: observability — OAuth account creation audit trail ──


def test_new_oauth_account_creation_is_logged(db_session, caplog):
    """Creating a brand-new user+business via OAuth must produce an audit line."""
    with caplog.at_level(logging.INFO, logger="app.routers.oauth"):
        result = _find_or_create_oauth_user(
            db_session,
            provider="google",
            oauth_id="obs-new-gid",
            email="obs-new@example.com",
            name="Observable User",
            email_verified=True,
        )

    assert result is not None
    assert any(
        "OAuth account created" in r.message
        and r.provider == "google"
        and r.user_id == result.id
        and r.business_id == result.business_id
        for r in caplog.records
    )


def test_oauth_provider_linking_is_logged(db_session, caplog):
    """Linking a new OAuth provider to an existing password account must be logged."""
    business = Business(legal_name="Link Obs Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="link-obs@example.com",
        hashed_password="bcrypt-hash-here",
        business_id=business.id,
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.routers.oauth"):
        result = _find_or_create_oauth_user(
            db_session,
            provider="github",
            oauth_id="link-obs-ghid",
            email="link-obs@example.com",
            name="Link Obs",
            email_verified=True,
        )

    assert result is not None
    assert any(
        "OAuth provider linked" in r.message
        and r.provider == "github"
        and r.user_id == user.id
        for r in caplog.records
    )


def test_returning_oauth_login_does_not_log_creation(db_session, caplog):
    """A returning OAuth user already has a provider set — no creation or linking."""
    business = Business(legal_name="Return Co", plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(
        email="returning@example.com",
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider="google",
        oauth_id="returning-gid",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.routers.oauth"):
        result = _find_or_create_oauth_user(
            db_session,
            provider="google",
            oauth_id="returning-gid",
            email="returning@example.com",
            name=None,
        )

    assert result is not None
    assert not any(
        "OAuth account created" in r.message or "OAuth provider linked" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# One account per provider identity (C103 M13)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, ""), ("", ""), ("  ", ""), (True, ""), (12345, "12345"), ("g-123", "g-123")],
)
def test_a_provider_id_is_text_or_nothing(raw, expected):
    # str(None) was "None": every GitHub profile without an id shared it.
    assert _provider_id(raw) == expected


def _user(db_session, email, **fields):
    business = Business(legal_name=email, plan=BusinessPlan.FREE, is_active=True)
    db_session.add(business)
    db_session.flush()
    user = User(email=email, business_id=business.id, role=UserRole.OWNER, is_active=True, **fields)
    db_session.add(user)
    return user


def test_one_provider_identity_cannot_be_linked_to_two_users(db_session):
    from sqlalchemy.exc import IntegrityError

    _user(db_session, "first@example.com", oauth_provider="google", oauth_id="g-1")
    db_session.commit()
    _user(db_session, "second@example.com", oauth_provider="google", oauth_id="g-1")
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_password_accounts_without_an_identity_are_not_in_each_others_way(db_session):
    _user(db_session, "a@example.com")
    _user(db_session, "b@example.com")
    db_session.commit()  # the index is partial: NULL identities never collide


def test_the_same_id_at_two_providers_is_two_identities(db_session):
    _user(db_session, "a@example.com", oauth_provider="google", oauth_id="42")
    _user(db_session, "b@example.com", oauth_provider="github", oauth_id="42")
    db_session.commit()


def test_a_github_profile_without_an_id_is_refused(client, caplog):
    """Before, it was stored and looked up as the identity "None"."""
    from unittest.mock import AsyncMock, MagicMock

    oauth_client = MagicMock()
    oauth_client.authorize_access_token = AsyncMock(return_value={"access_token": "t"})
    profile = MagicMock()
    profile.json.return_value = {"id": None, "email": "x@example.com", "login": "x"}
    oauth_client.get = AsyncMock(return_value=profile)
    with (
        patch("app.routers.oauth._configured_client", return_value=oauth_client),
        caplog.at_level(logging.WARNING, logger="app.routers.oauth"),
    ):
        response = client.get("/api/v1/auth/github/callback?code=c&state=s", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "error=github_auth_failed" in response.headers["location"]
    # Refused at the id check, not by an earlier step of the callback.
    assert any(r.getMessage() == "OAuth sign-in refused: no account id" for r in caplog.records)
