"""A password can be changed, and changing it ends the sessions it opened.

There was no way to change a password at all — only register and log in — so
a password that leaked could not be rotated short of someone editing the
database, and every token it had already issued stayed good for its full day.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.models.user import User
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

URL = "/api/v1/auth/change-password"
NEW = "a-different-long-passphrase"


def _login(client, password):
    return client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": password}
    )


def _me(client, token):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_the_old_password_stops_working_and_the_new_one_signs_in(auth_client):
    response = auth_client.post(URL, json={"current_password": TEST_PASSWORD, "new_password": NEW})
    assert response.status_code == 200, response.text
    assert _login(auth_client, TEST_PASSWORD).status_code == 401
    assert _login(auth_client, NEW).status_code == 200


def test_a_token_issued_before_the_change_is_refused(auth_client, monkeypatch):
    # The stolen-session case: a token the old password produced.
    old_token = auth_client.headers["Authorization"].removeprefix("Bearer ")
    # Issued a few seconds earlier, as any token in an attacker's hands was.
    claims = jwt.decode(old_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    claims["iat"] = int((datetime.now(UTC) - timedelta(seconds=5)).timestamp())
    old_token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert _me(auth_client, old_token).status_code == 200

    response = auth_client.post(URL, json={"current_password": TEST_PASSWORD, "new_password": NEW})
    assert response.status_code == 200

    assert _me(auth_client, old_token).status_code == 401
    # The caller stays signed in on the token the change hands back.
    assert _me(auth_client, response.json()["access_token"]).status_code == 200


def test_a_token_from_before_issued_at_existed_is_refused_after_a_change(auth_client):
    legacy = jwt.encode(
        {"sub": str(_user_id(auth_client)), "type": "access",
         "exp": datetime.now(UTC) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    assert _me(auth_client, legacy).status_code == 200  # untouched until a change
    auth_client.post(URL, json={"current_password": TEST_PASSWORD, "new_password": NEW})
    assert _me(auth_client, legacy).status_code == 401


def test_the_wrong_current_password_changes_nothing(auth_client):
    response = auth_client.post(
        URL, json={"current_password": "not-it-at-all", "new_password": NEW}
    )
    assert response.status_code == 400
    assert _login(auth_client, TEST_PASSWORD).status_code == 200


@pytest.mark.parametrize("new", ["password123", "short", "        "])
def test_the_new_password_meets_the_registration_rules(auth_client, new):
    response = auth_client.post(URL, json={"current_password": TEST_PASSWORD, "new_password": new})
    assert response.status_code == 422


def test_the_same_password_again_is_not_a_change(auth_client):
    response = auth_client.post(
        URL, json={"current_password": TEST_PASSWORD, "new_password": TEST_PASSWORD}
    )
    assert response.status_code == 422


def test_an_account_that_signs_in_with_a_provider_has_no_password_to_change(
    auth_client, db_session
):
    user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
    user.hashed_password = None
    db_session.commit()
    response = auth_client.post(URL, json={"current_password": "anything", "new_password": NEW})
    assert response.status_code == 400
    assert "sign-in provider" in response.json()["detail"]


def test_it_needs_a_session(client):
    assert client.post(URL, json={"current_password": "x", "new_password": NEW}).status_code == 401


def _user_id(client):
    return client.get("/api/v1/auth/me").json()["id"]


def test_a_change_that_lost_a_race_does_not_overwrite_the_one_that_won(
    auth_client, db_session, monkeypatch
):
    """Two changes verified against the same old password: only the first lands.

    The check is a bcrypt round — a quarter of a second — against the hash the
    request loaded, and the write afterwards was unconditional. So the owner
    rotating a leaked password and whoever leaked it, changing it at the same
    moment from a session the old one opened, both passed, and the later commit
    won. If that was the attacker's, the password the owner had just rotated
    to was gone and the attacker's was in its place.
    """
    from sqlalchemy import update

    from app.core.security import hash_password
    from app.routers import auth as auth_router

    owners = "the-owners-fresh-passphrase"
    real_verify = auth_router.verify_password

    def verify_while_the_owner_commits(plain, hashed):
        ok = real_verify(plain, hashed)
        # The owner's own change commits while this request is still checking.
        db_session.execute(
            update(User)
            .where(User.email == TEST_EMAIL)
            .values(hashed_password=hash_password(owners))
            .execution_options(synchronize_session=False)
        )
        db_session.commit()
        return ok

    monkeypatch.setattr(auth_router, "verify_password", verify_while_the_owner_commits)
    response = auth_client.post(URL, json={"current_password": TEST_PASSWORD, "new_password": NEW})
    monkeypatch.setattr(auth_router, "verify_password", real_verify)

    assert response.status_code == 409, response.text
    assert "access_token" not in response.json()
    assert _login(auth_client, owners).status_code == 200
    assert _login(auth_client, NEW).status_code == 401
