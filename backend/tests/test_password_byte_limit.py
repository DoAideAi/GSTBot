"""A password is accepted only if all of it is what protects the account.

bcrypt reads the first 72 bytes and ``security._prepare`` cuts every password
there, while registration and change-password accepted up to 128 characters —
"capped at 128 because bcrypt hashes only the first 72 bytes", though 128 ASCII
characters is already 56 bytes past it. Everything after byte 72 was ignored:
an 80-character passphrase was its first 72, and a Devanagari one (3 bytes a
character) was its first 24 characters. New passwords over 72 bytes are now
refused; existing ones still sign in, since login was never the problem.
"""
from __future__ import annotations

import pytest

from app.core.security import hash_password, verify_password
from tests.conftest import TEST_PASSWORD

REGISTER = "/api/v1/auth/register"
CHANGE = "/api/v1/auth/change-password"
HINDI = "मेराजीएसटीपासवर्डबहुतलंबाहै"  # 27 characters, 3 bytes each in UTF-8


def _register(client, password):
    return client.post(
        REGISTER,
        json={"email": "bytes@example.com", "password": password, "full_name": "Byte Tester"},
    )


def test_the_ignored_tail_is_real():
    # What the limit protects against: two passwords equal in their first 72
    # bytes are one password to bcrypt.
    stored = hash_password("a" * 72 + "the-part-you-thought-mattered")
    assert verify_password("a" * 72 + "anything-else-at-all", stored)


@pytest.mark.parametrize(
    "password",
    ["x" * 73, "correct-horse-battery-staple-" * 3, HINDI],
)
def test_registration_refuses_a_password_bcrypt_would_cut(client, password):
    assert len(password.encode("utf-8")) > 72
    response = _register(client, password)
    assert response.status_code == 422, response.text
    assert "72" in response.text


def test_exactly_72_bytes_is_accepted(client):
    assert _register(client, "y" * 72).status_code == 201


def test_a_short_indian_script_password_is_accepted(client):
    password = HINDI[:20]  # 60 bytes
    assert _register(client, password).status_code == 201


def test_change_password_refuses_one_bcrypt_would_cut(auth_client):
    response = auth_client.post(
        CHANGE, json={"current_password": TEST_PASSWORD, "new_password": HINDI}
    )
    assert response.status_code == 422, response.text


def test_an_existing_long_password_still_signs_in(client, db_session):
    # Accounts made before the limit keep working: login checks what bcrypt
    # stored, and refusing it now would lock their owners out.
    from app.models.user import User

    assert _register(client, "z" * 40).status_code == 201
    user = db_session.query(User).filter_by(email="bytes@example.com").one()
    user.hashed_password = hash_password("q" * 100)
    db_session.commit()
    response = client.post(
        "/api/v1/auth/login", data={"username": "bytes@example.com", "password": "q" * 100}
    )
    assert response.status_code == 200
