"""Signing out ends the session on the server, not only in the browser.

Logout was client-side: the frontend dropped its copy of the token and the
server never heard about it, so a token copied before sign-out — a shared
computer, an extension, a screenshot of devtools — stayed good for its full
lifetime after the user believed they had signed out.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.core.security import create_access_token
from app.models.revoked_token import RevokedToken

URL = "/api/v1/auth/logout"


def _token(client) -> str:
    return client.headers["Authorization"].removeprefix("Bearer ")


def _me(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_a_token_stops_working_after_it_signs_out(auth_client):
    token = _token(auth_client)
    assert _me(auth_client, token).status_code == 200

    assert auth_client.post(URL).status_code == 204

    assert _me(auth_client, token).status_code == 401


def test_signing_out_one_session_leaves_the_others(auth_client):
    # An owner and their CA on one login, or a phone and a laptop: signing out
    # of one must not sign the other out.
    other = _token(auth_client)
    me = _me(auth_client, other).json()["id"]
    this = create_access_token(me)
    assert auth_client.post(URL, headers={"Authorization": f"Bearer {this}"}).status_code == 204
    assert _me(auth_client, this).status_code == 401
    assert _me(auth_client, other).status_code == 200


def test_every_token_is_distinct(auth_client):
    me = _me(auth_client, _token(auth_client)).json()["id"]
    first, second = create_access_token(me), create_access_token(me)
    claims = [
        jwt.decode(t, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        for t in (first, second)
    ]
    assert claims[0]["jti"] and claims[0]["jti"] != claims[1]["jti"]


def test_signing_out_twice_is_harmless(auth_client):
    token = _token(auth_client)
    assert auth_client.post(URL).status_code == 204
    # The second attempt carries a revoked token, so it is not a session.
    assert auth_client.post(URL, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_it_needs_a_session(client):
    assert client.post(URL).status_code == 401


def test_the_revocation_list_forgets_tokens_that_have_expired(auth_client, db_session):
    db_session.add(
        RevokedToken(jti="stale", user_id=_me(auth_client, _token(auth_client)).json()["id"],
                     expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    db_session.commit()
    assert auth_client.post(URL).status_code == 204
    db_session.expire_all()
    remaining = {row.jti for row in db_session.query(RevokedToken).all()}
    assert "stale" not in remaining and len(remaining) == 1
