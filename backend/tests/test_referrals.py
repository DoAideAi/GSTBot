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
