"""Tests for the CA referral program endpoints."""
from __future__ import annotations

from tests.conftest import TEST_EMAIL


class TestReferralTrack:
    """POST /referrals/track — public, records a visit."""

    def test_unknown_code_is_not_tracked(self, client):
        r = client.post("/api/v1/referrals/track", json={"referral_code": "BOGUS"})
        assert r.status_code == 200
        assert r.json()["tracked"] is False
        assert r.json()["reason"] == "unknown_code"

    def test_valid_code_is_tracked(self, auth_client, client):
        code_resp = auth_client.get("/api/v1/referrals/my-code")
        code = code_resp.json()["referral_code"]

        r = client.post("/api/v1/referrals/track", json={"referral_code": code})
        assert r.status_code == 200
        assert r.json()["tracked"] is True

    def test_duplicate_ip_is_not_tracked_twice(self, auth_client, client):
        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]

        client.post("/api/v1/referrals/track", json={"referral_code": code})
        r = client.post("/api/v1/referrals/track", json={"referral_code": code})
        assert r.json()["tracked"] is False
        assert r.json()["reason"] == "already_tracked"

    def test_a_request_that_loses_the_race_is_already_tracked_not_a_500(
        self, auth_client, client, monkeypatch
    ):
        """Two requests from one visitor can both pass the read-first check; the
        unique constraint (migration 0013) rejects the second commit."""
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        real_commit = Session.commit
        calls = {"n": 0}

        def commit_that_loses_once(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("INSERT INTO referrals", {}, Exception("unique"))
            return real_commit(self)

        monkeypatch.setattr(Session, "commit", commit_that_loses_once)
        r = client.post("/api/v1/referrals/track", json={"referral_code": code})
        assert r.status_code == 200
        assert r.json() == {"tracked": False, "reason": "already_tracked"}

    def test_the_database_refuses_a_second_row_for_one_visitor(self, auth_client, db_session):
        import pytest
        from sqlalchemy.exc import IntegrityError

        from app.models.referral import Referral
        from app.models.user import User

        auth_client.get("/api/v1/referrals/my-code")
        user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
        db_session.add(Referral(referral_code="C1", referrer_user_id=user.id, visitor_ip_hash="h"))
        db_session.commit()
        db_session.add(Referral(referral_code="C1", referrer_user_id=user.id, visitor_ip_hash="h"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_empty_code_is_refused(self, client):
        r = client.post("/api/v1/referrals/track", json={"referral_code": ""})
        assert r.status_code == 422


class TestReferralMyCode:
    """GET /referrals/my-code — authenticated, generates a stable code."""

    def test_unauthenticated_is_refused(self, client):
        r = client.get("/api/v1/referrals/my-code")
        assert r.status_code == 401

    def test_returns_a_code(self, auth_client):
        r = auth_client.get("/api/v1/referrals/my-code")
        assert r.status_code == 200
        assert r.json()["referral_code"].startswith("CA-")

    def test_code_is_stable(self, auth_client):
        code1 = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        code2 = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        assert code1 == code2

    def test_a_code_claimed_by_a_concurrent_first_call_is_not_overwritten(
        self, auth_client, db_session, monkeypatch
    ):
        """Two first calls both read no code and each generated one; the later
        commit replaced the earlier, so a code already handed out — and maybe
        shared — stopped existing. The other request's claim is made here
        between this request's read and its write, which is where it lands
        when the two interleave."""
        from sqlalchemy import update

        from app.models.user import User
        from app.routers import referrals

        user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
        real_generate = referrals._generate_code

        def generate_while_another_request_claims_first():
            db_session.execute(
                update(User).where(User.id == user.id).values(referral_code="CA-first")
            )
            db_session.commit()
            return real_generate()

        monkeypatch.setattr(
            referrals, "_generate_code", generate_while_another_request_claims_first
        )
        r = auth_client.get("/api/v1/referrals/my-code")
        assert r.status_code == 200
        assert r.json()["referral_code"] == "CA-first"
        db_session.expire_all()
        assert db_session.get(User, user.id).referral_code == "CA-first"

    def test_the_code_that_stuck_still_tracks_visits(
        self, auth_client, client, db_session, monkeypatch
    ):
        from sqlalchemy import update

        from app.models.user import User
        from app.routers import referrals

        user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
        real_generate = referrals._generate_code

        def generate_while_another_request_claims_first():
            db_session.execute(
                update(User).where(User.id == user.id).values(referral_code="CA-first")
            )
            db_session.commit()
            return real_generate()

        monkeypatch.setattr(
            referrals, "_generate_code", generate_while_another_request_claims_first
        )
        auth_client.get("/api/v1/referrals/my-code")
        r = client.post("/api/v1/referrals/track", json={"referral_code": "CA-first"})
        assert r.json() == {"tracked": True}


class TestReferralMyStats:
    """GET /referrals/my-stats — authenticated, shows the caller's stats."""

    def test_unauthenticated_is_refused(self, client):
        r = client.get("/api/v1/referrals/my-stats")
        assert r.status_code == 401

    def test_no_code_yet_returns_zeros(self, auth_client, db_session):
        from app.models.user import User
        user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
        user.referral_code = None
        db_session.commit()

        r = auth_client.get("/api/v1/referrals/my-stats")
        assert r.status_code == 200
        data = r.json()
        assert data["referral_code"] is None
        assert data["total_visits"] == 0

    def test_stats_reflect_tracked_visits(self, auth_client, client):
        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        client.post("/api/v1/referrals/track", json={"referral_code": code})

        r = auth_client.get("/api/v1/referrals/my-stats")
        assert r.json()["total_visits"] == 1
        assert r.json()["conversions"] == 0


class TestReferralLeaderboard:
    """GET /referrals/leaderboard — public, top referring CAs."""

    def test_empty_leaderboard(self, client):
        r = client.get("/api/v1/referrals/leaderboard")
        assert r.status_code == 200
        assert r.json()["leaders"] == []

    def test_leaderboard_shows_referrers(self, auth_client, client):
        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        client.post("/api/v1/referrals/track", json={"referral_code": code})

        r = client.get("/api/v1/referrals/leaderboard")
        assert r.status_code == 200
        leaders = r.json()["leaders"]
        assert len(leaders) == 1
        assert leaders[0]["referral_count"] == 1


class TestASignupConvertsTheVisit:
    """P17 M3: a referral visit had a ``converted`` state, ``/my-stats`` counted
    it and the referral page shows it as "Signups" — and nothing ever moved a
    visit into it, so every CA saw 0. Signing up now converts the visitor's
    latest visit, matched the way ``/track`` recognised it."""

    def _referrer(self, auth_client):
        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        token = auth_client.headers["Authorization"]
        return code, token

    def _signup(self, client, email="newcomer@example.com"):
        client.headers.pop("Authorization", None)
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "a-long-passphrase", "legal_name": "Newcomer"},
        )
        assert response.status_code == 201, response.text

    def _stats(self, client, token):
        return client.get("/api/v1/referrals/my-stats", headers={"Authorization": token}).json()

    def test_a_visit_followed_by_a_signup_counts_once(self, auth_client):
        code, token = self._referrer(auth_client)
        auth_client.headers.pop("Authorization")
        assert auth_client.post(
            "/api/v1/referrals/track", json={"referral_code": code}
        ).json()["tracked"]

        self._signup(auth_client)
        assert self._stats(auth_client, token) == {
            "referral_code": code,
            "total_visits": 1,
            "conversions": 1,
        }

        self._signup(auth_client, email="second@example.com")
        # The visit converted once; a second sign-up from that address is not
        # a second conversion of it.
        assert self._stats(auth_client, token)["conversions"] == 1

    def test_a_signup_with_no_visit_converts_nothing(self, auth_client):
        code, token = self._referrer(auth_client)
        self._signup(auth_client)
        assert self._stats(auth_client, token)["conversions"] == 0

    def test_a_visit_older_than_the_window_does_not_convert(self, auth_client, db_session):
        from datetime import UTC, datetime

        from app.models.referral import Referral
        from app.routers.referrals import CONVERSION_WINDOW

        code, token = self._referrer(auth_client)
        auth_client.headers.pop("Authorization")
        auth_client.post("/api/v1/referrals/track", json={"referral_code": code})
        visit = db_session.query(Referral).one()
        visit.created_at = datetime.now(UTC) - CONVERSION_WINDOW - CONVERSION_WINDOW / 30
        db_session.commit()

        self._signup(auth_client)
        assert self._stats(auth_client, token)["conversions"] == 0

    def test_a_failure_to_record_it_does_not_fail_the_signup(self, client, monkeypatch):
        from app.routers import referrals

        def broken(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(referrals, "_hash_ip", broken)
        self._signup(client)

    def test_a_visit_converted_by_a_concurrent_signup_is_not_claimed_twice(
        self, auth_client, db_session, monkeypatch
    ):
        # P17 M9: both sign-ups find the same open visit; the UPDATE is
        # conditional on it still being open, so the second converts nothing
        # and says so rather than reporting a conversion it lost.
        from app.models.referral import Referral
        from app.routers import referrals

        code, _ = self._referrer(auth_client)
        auth_client.headers.pop("Authorization")
        auth_client.post("/api/v1/referrals/track", json={"referral_code": code})
        visit = db_session.query(Referral).one()

        assert referrals.record_conversion(db_session, "testclient") is True
        # The loser read the visit before the winner committed:
        monkeypatch.setattr(db_session, "scalar", lambda *_a, **_k: visit.id)
        assert referrals.record_conversion(db_session, "testclient") is False
        db_session.expire_all()
        assert db_session.query(Referral).filter_by(converted=True).count() == 1


class TestTheVisitorKeyIsNotTheAddress:
    """P17 M16: the stored key was a bare SHA-256 of the visitor's IP, which is
    reversed by hashing every IPv4 address. It is now keyed with a server
    secret, and read through the same ``client_ip`` the rate limiter uses."""

    def test_the_stored_key_is_not_a_plain_hash_of_the_address(self, auth_client, db_session):
        import hashlib

        from app.models.referral import Referral

        code = auth_client.get("/api/v1/referrals/my-code").json()["referral_code"]
        auth_client.headers.pop("Authorization")
        auth_client.post("/api/v1/referrals/track", json={"referral_code": code})
        stored = db_session.query(Referral).one().visitor_ip_hash

        plain = hashlib.sha256(b"testclient").hexdigest()
        assert not plain.startswith(stored) and stored not in plain

    def test_the_key_depends_on_the_server_secret(self, monkeypatch):
        from app.core.config import settings
        from app.routers.referrals import _hash_ip

        first = _hash_ip("203.0.113.7")
        monkeypatch.setattr(settings, "jwt_secret", "another-long-secret-value-for-this-test-x")
        assert _hash_ip("203.0.113.7") != first

    def test_a_trusted_proxy_s_address_is_the_one_tracked(self, client, auth_client, monkeypatch):
        from app.core.config import settings
        from app.routers.referrals import visitor_ip

        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        class _Req:
            headers = {"x-real-ip": "198.51.100.9"}
            client = type("C", (), {"host": "172.18.0.13"})()

        assert visitor_ip(_Req()) == "198.51.100.9"


def test_the_conversion_lookup_has_an_index_that_leads_with_the_visitor():
    # P17 M8: record_conversion runs on every sign-up and filters by visitor,
    # ordered by time. The unique (code, visitor) index leads with the code and
    # cannot serve that, so each sign-up scanned a publicly-grown table.
    from app.models.referral import Referral

    leading = {
        tuple(column.name for column in index.columns)[:2]
        for index in Referral.__table__.indexes
    }
    assert ("visitor_ip_hash", "created_at") in leading


class TestThePublicLeaderboardNamesNoOne:
    """P23 M10: a referrer with no name was shown as their email's local part
    on a public page, and a whitespace-only name took the endpoint down with
    an IndexError for every visitor while that user ranked."""

    def _rank(self, db_session, business, *people):
        from app.models.referral import Referral
        from app.models.user import User

        for i, (name, email, active) in enumerate(people):
            user = User(
                email=email,
                full_name=name,
                hashed_password="x",
                business_id=business.id,
                is_active=active,
            )
            db_session.add(user)
            db_session.flush()
            for j in range(len(people) - i):
                db_session.add(
                    Referral(
                        referrer_user_id=user.id, referral_code=f"c{i}", visitor_ip_hash=f"{i}{j}"
                    )
                )
        db_session.commit()

    def test_no_name_is_never_the_email_and_blank_is_not_a_500(
        self, raw_client, db_session, business
    ):
        self._rank(
            db_session,
            business,
            ("   ", "blank@example.com", True),
            (None, "suman.sharma1990@example.com", True),
            ("​", "invisible@example.com", True),
            ("Asha Kumari Rao", "asha@example.com", True),
        )
        response = raw_client.get("/api/v1/referrals/leaderboard")
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["leaders"]]
        assert names == ["A DoAide GST user"] * 3 + ["Asha R."]
        assert "suman" not in response.text and "@" not in response.text

    def test_a_deactivated_account_is_not_listed(self, raw_client, db_session, business):
        self._rank(
            db_session,
            business,
            ("Gone Away", "gone@example.com", False),
            ("Still Here", "here@example.com", True),
        )
        board = raw_client.get("/api/v1/referrals/leaderboard").json()
        assert [row["name"] for row in board["leaders"]] == ["Still H."]
