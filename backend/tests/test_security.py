"""Password hashing and access tokens, tested directly.

These are exercised through /auth already, but only along the paths a working
client takes. What matters here is the other kind of input: a corrupt hash out
of the database, a token signed with somebody else's secret, a token that was
minted for a different purpose. Each of those is a way in if it is handled
loosely, and none of them is reachable from the HTTP tests.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_a_password_verifies_against_its_own_hash(self):
        assert verify_password("supersecret123", hash_password("supersecret123"))

    def test_a_wrong_password_does_not(self):
        assert not verify_password("supersecret124", hash_password("supersecret123"))

    def test_the_same_password_hashes_differently_every_time(self):
        """Distinct salts. Equal hashes would let anyone read the database see
        which accounts share a password."""
        assert hash_password("supersecret123") != hash_password("supersecret123")

    def test_a_corrupt_stored_hash_is_a_failed_login_not_a_500(self):
        """A truncated or hand-edited row must deny the login, not crash it.

        bcrypt raises on a malformed hash; letting that escape turns one bad
        row into a 500 that looks like the whole API is down.
        """
        assert not verify_password("supersecret123", "not-a-bcrypt-hash")
        assert not verify_password("supersecret123", "")

    def test_a_password_longer_than_bcrypt_accepts_still_works(self):
        """bcrypt reads at most 72 bytes and historically errored past that."""
        password = "a" * 200

        assert verify_password(password, hash_password(password))

    def test_a_long_multibyte_password_does_not_break_on_the_byte_boundary(self):
        """Truncating to 72 *bytes* can cut a character in half.

        bcrypt takes bytes, so that is harmless — but only if the truncation
        happens before the encode is decoded again anywhere.
        """
        password = "पासवर्ड" * 20

        assert verify_password(password, hash_password(password))

    def test_two_long_passwords_sharing_a_prefix_are_not_distinguished(self):
        """A known bcrypt property, asserted so it is a decision and not a
        surprise: beyond 72 bytes the tail is ignored. The registration schema
        is what bounds password length; this is not a place to rely on it."""
        base = "a" * 72

        assert verify_password(base + "different", hash_password(base + "tail"))


def cost_factor(digest: str) -> int:
    """The rounds bcrypt recorded in *digest* — ``"$2b$12$...."`` -> ``12``."""
    return int(digest.split("$")[2])


class TestTheConfiguredCostFactor:
    """``BCRYPT_ROUNDS`` exists so the suite is not mostly key stretching.

    That makes it the one security parameter deliberately weakened under test,
    so the tests that keep it honest have to be the ones that do not care what
    it is currently set to. Two things must hold: the setting is really what
    reaches bcrypt (a hash pinned to a hard-coded factor would sail through
    every other test in this file), and lowering it for the suite has not
    quietly changed what a *stored* hash is worth.

    The floor that keeps the test value out of production is asserted in
    ``test_config.py``; here it is only the wiring.
    """

    def test_the_hash_records_the_factor_the_settings_ask_for(self):
        assert cost_factor(hash_password("supersecret123")) == settings.bcrypt_rounds

    def test_raising_the_setting_makes_a_more_expensive_hash(self, monkeypatch):
        """Read per call, not captured at import.

        A factor read once at module import would be right in every process
        that never changes it — including this suite — and would silently
        ignore an operator raising it, which is the only reason the setting is
        tunable at all.
        """
        monkeypatch.setattr(settings, "bcrypt_rounds", 6)
        cheap = hash_password("supersecret123")
        monkeypatch.setattr(settings, "bcrypt_rounds", 7)
        dearer = hash_password("supersecret123")

        assert cost_factor(cheap) == 6
        assert cost_factor(dearer) == 7

    def test_a_hash_written_at_another_factor_still_verifies(self, monkeypatch):
        """Raising the factor must not lock existing accounts out.

        bcrypt encodes the cost in the hash, so verification needs no setting
        at all — which is what makes raising it a config change rather than a
        migration. If this ever fails, every account that has not changed its
        password since the last change is locked out, and the failure arrives
        at login rather than at deploy.
        """
        monkeypatch.setattr(settings, "bcrypt_rounds", 5)
        stored = hash_password("supersecret123")

        monkeypatch.setattr(settings, "bcrypt_rounds", 8)
        assert verify_password("supersecret123", stored)
        assert not verify_password("supersecret124", stored)

    def test_the_suite_is_not_running_at_the_production_factor(self):
        """Guards the speed-up itself.

        The point of the setting is that the suite stops paying for real key
        stretching, and nothing else notices if a conftest edit or a stray
        BCRYPT_ROUNDS in the environment puts it back — the suite would only
        get slower, which reads as a bad day on CI rather than as a
        regression. `pyproject.toml`'s coverage gate is a ratchet for the same
        reason.
        """
        assert settings.bcrypt_rounds == 4


class TestVerifyingAgainstNoAccount:
    """``verify_password(plain, None)`` — the "no such user" path.

    Returning early there is the obvious implementation and it is a user
    enumeration oracle: bcrypt costs a few hundred milliseconds, a missing row
    costs nothing, and the difference is measurable across the internet. So the
    absent case does the same work, and these tests are what say so — a login
    that skips the hashing still returns the same 401 body and would pass every
    test in ``test_auth.py`` written before this one.
    """

    def test_no_account_is_a_failed_verification(self):
        assert not verify_password("supersecret123", None)

    def test_the_absent_case_still_runs_a_full_bcrypt_comparison(self, monkeypatch):
        """The property, asserted on the work done rather than on the clock.

        A wall-clock assertion is the direct translation and is unusable in
        CI — a loaded runner makes it either flaky or so loose it proves
        nothing. Counting the bcrypt calls is exact, and it fails for exactly
        the change that matters: an early return when the row is missing.
        """
        import app.core.security as security

        calls: list[bytes] = []
        real = security.bcrypt.checkpw

        def spy(password, hashed):
            calls.append(hashed)
            return real(password, hashed)

        monkeypatch.setattr(security.bcrypt, "checkpw", spy)
        security._absent_account_hash()  # Pay the lazy build outside the count.
        calls.clear()

        assert not verify_password("supersecret123", None)
        assert len(calls) == 1

        present = hash_password("supersecret123")
        calls.clear()
        assert verify_password("supersecret123", present)
        assert len(calls) == 1

    def test_the_stand_in_hash_costs_what_a_real_one_costs(self):
        """Equal work means the same bcrypt cost factor.

        A stand-in built at a cheaper cost would still be one ``checkpw`` call
        and would still be several times faster than a stored hash, which puts
        the timing gap straight back.
        """
        import app.core.security as security

        def cost(digest: str) -> str:
            # "$2b$12$...." — scheme and rounds are the first three fields.
            return "$".join(digest.split("$")[:3])

        assert cost(security._absent_account_hash()) == cost(hash_password("anything"))

    def test_the_stand_in_hash_is_reused_rather_than_rebuilt(self):
        """Rebuilding it per call would double the cost of every failed login
        against an unknown address — which is the request an attacker sends
        most of, and so is the one worth not making expensive for us."""
        import app.core.security as security

        assert security._absent_account_hash() is security._absent_account_hash()

    def test_nothing_verifies_against_the_stand_in_hash(self):
        """It is a hash of a fresh random secret, so there is no password that
        opens it — including the empty one a caller can actually send."""
        import app.core.security as security

        absent = security._absent_account_hash()

        assert not verify_password("", absent)
        assert not verify_password("supersecret123", absent)

    def test_two_processes_do_not_share_a_stand_in_hash(self, monkeypatch):
        """Built from ``secrets.token_urlsafe``, so it is not a constant baked
        into the source that anyone reading the repository could match."""
        import app.core.security as security

        first = security._absent_account_hash()
        monkeypatch.setattr(security, "_absent_hash", None)
        assert security._absent_account_hash() != first

    def test_a_caller_that_loses_the_race_reuses_what_the_winner_minted(self, monkeypatch):
        """The check inside the lock is not a redundant copy of the one outside.

        They guard different things. The outer check keeps every later call off
        the lock at all; the inner one is what a thread that *blocked* on the
        lock runs once the winner has released it. Without it that thread mints
        a second hash and overwrites the first — so a burst of failed logins,
        which is precisely the traffic this stand-in exists for, pays the full
        bcrypt cost once per concurrent request instead of once per process,
        and does it on the workers already contending for the lock.

        The race is forced rather than run. A lock whose acquisition fills the
        global is what losing looks like from inside this function, and it is
        deterministic where real threads would not be.
        """
        import app.core.security as security

        monkeypatch.setattr(security, "_absent_hash", None)
        winners_hash = hash_password("what the thread that got there first minted")

        class _LockTheWinnerHasAlreadyPassedThrough:
            def __enter__(self):
                security._absent_hash = winners_hash
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(
            security, "_absent_hash_lock", _LockTheWinnerHasAlreadyPassedThrough()
        )

        assert security._absent_account_hash() == winners_hash

    def test_the_lock_is_held_only_when_there_is_nothing_to_return(self, monkeypatch):
        """The common call is a read of an already-built hash, and it happens
        on every failed login. Taking the lock for it would serialise the whole
        worker behind a value that stopped changing at startup."""
        import app.core.security as security

        entries = []

        class _CountingLock:
            def __enter__(self):
                entries.append(1)
                security._absent_hash = hash_password("built under the lock")
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(security, "_absent_hash", None)
        monkeypatch.setattr(security, "_absent_hash_lock", _CountingLock())

        security._absent_account_hash()
        security._absent_account_hash()
        security._absent_account_hash()

        assert entries == [1]


class TestAccessTokens:
    def test_a_token_round_trips_to_its_subject(self):
        assert decode_access_token(create_access_token(42)) == "42"

    def test_an_integer_subject_comes_back_as_a_string(self):
        """`sub` is a string claim by spec, and callers compare it as one."""
        assert decode_access_token(create_access_token(42)) == "42"

    def test_garbage_is_rejected(self):
        assert decode_access_token("not.a.token") is None

    def test_an_empty_token_is_rejected(self):
        assert decode_access_token("") is None

    def test_a_token_signed_with_another_secret_is_rejected(self):
        """The signature is the only thing standing between a forged `sub` and
        a session as that user."""
        forged = jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=30), "type": "access"},
            "a-different-secret",
            algorithm=settings.jwt_algorithm,
        )

        assert decode_access_token(forged) is None

    def test_an_expired_token_is_rejected(self):
        assert decode_access_token(create_access_token(1, expires_minutes=-1)) is None

    def test_a_token_minted_for_another_purpose_is_not_an_access_token(self):
        """The `type` claim is checked, not just the signature.

        A refresh or password-reset token is signed with the same secret. If
        `type` went unchecked, any of them would authenticate as its subject —
        which is exactly what a reset token must never do.
        """
        other = jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=30), "type": "refresh"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        assert decode_access_token(other) is None

    def test_a_token_with_no_type_claim_is_rejected(self):
        untyped = jwt.encode(
            {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=30)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        assert decode_access_token(untyped) is None

    @pytest.mark.parametrize("algorithm", ["none", "HS512"])
    def test_a_token_using_a_different_algorithm_is_rejected(self, algorithm):
        """`algorithms=` is pinned on decode. Accepting whatever the token's
        own header asks for is the classic JWT hole — `alg: none` most of all.
        """
        if algorithm == "none":
            # Built by hand the way an attacker would, rather than through the
            # library under test.
            import base64
            import json

            def segment(payload):
                raw = json.dumps(payload, separators=(",", ":")).encode()
                return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

            header = segment({"alg": "none", "typ": "JWT"})
            claims = segment({"sub": "1", "type": "access"})
            token = f"{header}.{claims}."
        else:
            token = jwt.encode(
                {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=30), "type": "access"},
                settings.jwt_secret,
                algorithm=algorithm,
            )

        assert decode_access_token(token) is None

    def test_a_token_from_before_the_pyjwt_switch_still_decodes(self):
        """Sessions issued under python-jose must survive the move to PyJWT.

        Built to the JWS spec by hand — base64url header and claims, HMAC-SHA256
        over them with the secret — so it stands for any HS256 token, whichever
        library minted it.
        """
        import base64
        import hashlib
        import hmac
        import json

        def segment(raw: bytes) -> str:
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

        exp = int((datetime.now(UTC) + timedelta(minutes=30)).timestamp())
        header = segment(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        claims = segment(json.dumps({"sub": "42", "exp": exp, "type": "access"}).encode())
        signing_input = f"{header}.{claims}".encode()
        signature = segment(
            hmac.new(settings.jwt_secret.encode(), signing_input, hashlib.sha256).digest()
        )

        assert decode_access_token(f"{header}.{claims}.{signature}") == "42"

    def test_the_expiry_honours_an_explicit_override(self):
        token = create_access_token(1, expires_minutes=90)
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        expires_in = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)

        assert timedelta(minutes=88) < expires_in <= timedelta(minutes=90)

    def test_the_expiry_falls_back_to_the_configured_default(self):
        token = create_access_token(1)
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        expires_in = datetime.fromtimestamp(claims["exp"], UTC) - datetime.now(UTC)

        assert expires_in <= timedelta(minutes=settings.access_token_expire_minutes)


# ── GB027: session key must be derived, not reused ──────────


class TestSessionKeyDerivation:
    def test_derived_key_differs_from_jwt_secret(self):
        """SessionMiddleware must not use the raw JWT secret."""
        from app.main import derive_session_key

        derived = derive_session_key(settings.jwt_secret)
        assert derived != settings.jwt_secret

    def test_derived_key_is_deterministic(self):
        from app.main import derive_session_key

        assert derive_session_key("test-secret") == derive_session_key("test-secret")

    def test_different_jwt_secrets_produce_different_session_keys(self):
        from app.main import derive_session_key

        assert derive_session_key("secret-a") != derive_session_key("secret-b")

    def test_session_middleware_uses_derived_key(self):
        """The app must wire the derived key, not the raw JWT secret."""
        from starlette.middleware.sessions import SessionMiddleware

        from app.main import create_app, derive_session_key

        application = create_app()
        expected = derive_session_key(settings.jwt_secret)
        for mw in application.user_middleware:
            if mw.cls is SessionMiddleware:
                assert mw.kwargs["secret_key"] == expected
                break
        else:
            pytest.fail("SessionMiddleware not found in middleware stack")
