"""A forgotten password can be reset, by the person who holds the address.

There was no way back from a forgotten password: no reset, no recovery, and
since P32 M1 a password account cannot be entered through Google either. A
user who forgot it was locked out of their books for good.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import jwt
import pytest

from app.core.config import settings
from app.routers import auth as auth_router
from tests.conftest import TEST_EMAIL, TEST_PASSWORD

FORGOT = "/api/v1/auth/forgot-password"
RESET = "/api/v1/auth/reset-password"
NEW = "a-fresh-long-passphrase"


@pytest.fixture
def outbox(monkeypatch):
    monkeypatch.setattr(settings, "alerts_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    sent: list[dict] = []

    def fake_send(*, to, subject, body, headers=None):
        sent.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(auth_router, "send_email", fake_send)
    return sent


def _token_from(message) -> str:
    link = next(word for word in message["body"].split() if "/reset-password#token=" in word)
    parts = urlsplit(link)
    assert parts.path == "/reset-password" and parts.query == ""  # never in a logged URL
    return parts.fragment.removeprefix("token=")


def _login(client, password):
    return client.post("/api/v1/auth/login", data={"username": TEST_EMAIL, "password": password})


def test_the_holder_of_the_address_is_emailed_a_link(auth_client, outbox):
    response = auth_client.post(FORGOT, json={"email": TEST_EMAIL.upper()})

    assert response.status_code == 202
    assert [m["to"] for m in outbox] == [TEST_EMAIL]
    assert _token_from(outbox[0])


def test_an_unknown_address_gets_the_same_answer_and_no_email(auth_client, outbox):
    known = auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    unknown = auth_client.post(FORGOT, json={"email": "nobody@example.com"})

    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert len(outbox) == 1


def test_the_link_sets_a_new_password_and_signs_in(auth_client, outbox):
    auth_client.post(FORGOT, json={"email": TEST_EMAIL})

    response = auth_client.post(RESET, json={"token": _token_from(outbox[0]), "new_password": NEW})

    assert response.status_code == 200, response.text
    me = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert _login(auth_client, TEST_PASSWORD).status_code == 401
    assert _login(auth_client, NEW).status_code == 200


def test_a_link_works_once(auth_client, outbox):
    auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    token = _token_from(outbox[0])
    assert auth_client.post(RESET, json={"token": token, "new_password": NEW}).status_code == 200

    again = auth_client.post(RESET, json={"token": token, "new_password": "another-passphrase-2"})

    assert again.status_code == 400
    assert _login(auth_client, NEW).status_code == 200


def test_the_sessions_the_old_password_opened_end(auth_client, outbox):
    old = auth_client.headers["Authorization"]
    claims = jwt.decode(old.removeprefix("Bearer "), settings.jwt_secret,
                        algorithms=[settings.jwt_algorithm])
    claims["iat"] = int((datetime.now(UTC) - timedelta(seconds=5)).timestamp())
    old = "Bearer " + jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    auth_client.post(RESET, json={"token": _token_from(outbox[0]), "new_password": NEW})

    assert auth_client.get("/api/v1/auth/me", headers={"Authorization": old}).status_code == 401


def test_an_expired_link_is_refused(auth_client, outbox, monkeypatch):
    auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    token = _token_from(outbox[0])
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
    expired = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    assert auth_client.post(RESET, json={"token": expired, "new_password": NEW}).status_code == 400


def test_a_session_token_is_not_a_reset_link_nor_the_reverse(auth_client, outbox):
    session = auth_client.headers["Authorization"].removeprefix("Bearer ")
    assert auth_client.post(RESET, json={"token": session, "new_password": NEW}).status_code == 400

    auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    reset = _token_from(outbox[0])
    me = auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {reset}"})
    assert me.status_code == 401


def test_the_new_password_meets_the_registration_rules(auth_client, outbox):
    auth_client.post(FORGOT, json={"email": TEST_EMAIL})
    token = _token_from(outbox[0])
    weak = auth_client.post(RESET, json={"token": token, "new_password": "password"})
    assert weak.status_code == 422


def test_an_account_with_no_password_is_sent_nothing(auth_client, outbox, db_session):
    from app.models.user import User

    user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
    user.hashed_password = None
    user.oauth_provider, user.oauth_id = "google", "g-1"
    db_session.commit()

    assert auth_client.post(FORGOT, json={"email": TEST_EMAIL}).status_code == 202
    assert outbox == []


def test_where_email_is_off_it_still_answers_and_sends_nothing(auth_client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "alerts_email_enabled", False)
    assert auth_client.post(FORGOT, json={"email": TEST_EMAIL}).status_code == 202
    assert outbox == []


class TestOneInboxCannotBeFlooded:
    """P34 M1: the reset email was limited per caller's IP, and only that.

    Five an hour from one address, unlimited across addresses: anyone rotating
    IPs could send a victim reset email after reset email, every one through
    this product's relay and against its sending reputation. P33 M16's commit
    said "rate-limited per address"; it was not. Past the per-address budget
    nothing is sent — and the answer stays the same 202, so the budget cannot
    be used to tell which addresses have accounts.
    """

    def test_an_address_gets_a_few_links_an_hour_however_many_callers_ask(
        self, auth_client, outbox, rate_limited, pinned_window, monkeypatch
    ):
        # As if every request came from a different host: the per-IP limit
        # is out of the way, so only the per-address budget is under test.
        monkeypatch.setattr(settings, "rate_limit_overrides", "forgot_password=1000/hour")

        answers = [auth_client.post(FORGOT, json={"email": TEST_EMAIL}) for _ in range(8)]

        assert {a.status_code for a in answers} == {202}
        assert len({a.text for a in answers}) == 1
        assert len(outbox) == auth_router.RESET_EMAILS_PER_ADDRESS

    def test_another_address_has_its_own_budget(
        self, auth_client, client, outbox, rate_limited, pinned_window, monkeypatch
    ):
        monkeypatch.setattr(settings, "rate_limit_overrides", "forgot_password=1000/hour")
        for _ in range(auth_router.RESET_EMAILS_PER_ADDRESS + 2):
            auth_client.post(FORGOT, json={"email": TEST_EMAIL})
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "second@example.com",
                "password": "another-long-pass1",
                "legal_name": "S",
            },
        )

        auth_client.post(FORGOT, json={"email": "second@example.com"})

        assert outbox[-1]["to"] == "second@example.com"

    def test_an_unknown_address_spends_nothing_that_shows(
        self, auth_client, outbox, rate_limited, pinned_window, monkeypatch
    ):
        monkeypatch.setattr(settings, "rate_limit_overrides", "forgot_password=1000/hour")
        unknown = [auth_client.post(FORGOT, json={"email": "nobody@example.com"}) for _ in range(6)]
        known = auth_client.post(FORGOT, json={"email": TEST_EMAIL})

        assert {a.text for a in unknown} == {known.text}
