"""Subscriber email capture and unsubscribe endpoints."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.subscriber import Subscriber
from app.routers.misc import make_unsubscribe_token
from app.schemas.misc import SubscriberRequest


class TestSubscribe:
    """POST /api/v1/subscribers — email capture from public pages."""

    def test_a_new_email_is_subscribed(self, client):
        r = client.post(
            "/api/v1/subscribers", json={"email": "new@example.com", "source": "calculator"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["subscribed"] is True
        assert body["new"] is True

    def test_a_duplicate_email_is_accepted_idempotently(self, client):
        client.post("/api/v1/subscribers", json={"email": "dup@example.com"})
        r = client.post("/api/v1/subscribers", json={"email": "dup@example.com"})
        assert r.status_code == 200
        assert r.json()["new"] is False
        assert r.json()["subscribed"] is True

    def test_a_double_submit_that_loses_the_race_is_a_duplicate_not_a_409(
        self, client, monkeypatch
    ):
        """Both requests of a double click can pass the read-first check; the
        unique index on ``email`` rejects the second commit."""
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        real_commit = Session.commit
        calls = {"n": 0}

        def commit_that_loses_once(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("INSERT INTO subscribers", {}, Exception("unique"))
            return real_commit(self)

        monkeypatch.setattr(Session, "commit", commit_that_loses_once)
        r = client.post("/api/v1/subscribers", json={"email": "twice@example.com"})
        assert r.status_code == 200
        assert r.json()["subscribed"] is True
        assert r.json()["new"] is False

    def test_email_is_normalised_to_lowercase(self, client):
        client.post("/api/v1/subscribers", json={"email": "Upper@Example.COM"})
        r = client.post("/api/v1/subscribers", json={"email": "upper@example.com"})
        assert r.json()["new"] is False

    def test_invalid_email_is_rejected(self, client):
        r = client.post("/api/v1/subscribers", json={"email": "not-an-email"})
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "source", ["<script>", "Has Space", "UPPER", "a" * 51, "-leading", "", "dot.ted"]
    )
    def test_a_source_that_is_not_a_short_slug_is_rejected(self, client, source):
        r = client.post("/api/v1/subscribers", json={"email": "s@x.com", "source": source})
        assert r.status_code == 422

    def test_a_tool_pages_own_source_is_accepted(self, client, db_session):
        # It was an allow-list of four, and the tool pages send their own:
        # every sign-up from the e-way bill page, the ITC calculators, the
        # return calendar — 42 of the 46 forms — was refused with a 422.
        r = client.post("/api/v1/subscribers", json={"email": "e@x.com", "source": "eway-bill"})
        assert r.status_code in (200, 201), r.text
        sub = db_session.query(Subscriber).filter_by(email="e@x.com").one()
        assert sub.source == "eway-bill"

    def test_source_defaults_to_landing(self, client, db_session):
        client.post("/api/v1/subscribers", json={"email": "default@example.com"})
        from app.models.subscriber import Subscriber
        sub = db_session.query(Subscriber).filter_by(email="default@example.com").first()
        assert sub is not None
        assert sub.source == "landing"

    def test_resubscribe_after_unsubscribe(self, client, db_session):
        client.post("/api/v1/subscribers", json={"email": "bounce@example.com"})
        from app.models.subscriber import Subscriber
        sub = db_session.query(Subscriber).filter_by(email="bounce@example.com").one()
        from app.models.mixins import utcnow
        sub.unsubscribed_at = utcnow()
        db_session.commit()

        r = client.post("/api/v1/subscribers", json={"email": "bounce@example.com"})
        assert r.json()["new"] is True
        db_session.refresh(sub)
        assert sub.unsubscribed_at is None


    def test_resubscribing_keeps_the_first_signup_and_stamps_the_change(
        self, client, db_session
    ):
        """``subscribed_at`` is rewritten on resubscribe, so it cannot say when
        the address first signed up; ``created_at`` and ``updated_at`` can."""
        from datetime import UTC, datetime

        from app.models.mixins import utcnow
        from app.models.subscriber import Subscriber

        client.post("/api/v1/subscribers", json={"email": "returning@example.com"})
        sub = db_session.query(Subscriber).filter_by(email="returning@example.com").one()
        long_ago = datetime(2025, 1, 1, tzinfo=UTC)
        sub.created_at = long_ago
        sub.unsubscribed_at = utcnow()
        db_session.commit()
        sub.updated_at = long_ago  # after the commit's onupdate, so it sticks
        db_session.commit()

        client.post("/api/v1/subscribers", json={"email": "returning@example.com"})
        db_session.refresh(sub)
        assert sub.created_at.replace(tzinfo=UTC) == long_ago
        assert sub.updated_at.replace(tzinfo=UTC) > long_ago


class TestUnsubscribe:
    """GET /api/v1/subscribers/unsubscribe?email=...&token=..."""

    def test_valid_token_unsubscribes(self, client):
        client.post("/api/v1/subscribers", json={"email": "unsub@example.com"})
        token = make_unsubscribe_token("unsub@example.com")
        r = client.get(f"/api/v1/subscribers/unsubscribe?email=unsub@example.com&token={token}")
        assert r.status_code == 200
        assert r.json()["unsubscribed"] is True

    def test_wrong_token_is_rejected(self, client):
        client.post("/api/v1/subscribers", json={"email": "wrong@example.com"})
        bad_token = "a" * 64
        r = client.get(f"/api/v1/subscribers/unsubscribe?email=wrong@example.com&token={bad_token}")
        assert r.status_code == 200
        assert r.json()["unsubscribed"] is False
        assert "Invalid" in r.json()["error"]

    def test_unknown_email_is_reported(self, client):
        token = make_unsubscribe_token("ghost@example.com")
        r = client.get(f"/api/v1/subscribers/unsubscribe?email=ghost@example.com&token={token}")
        assert r.json()["unsubscribed"] is False
        assert "not found" in r.json()["error"]

    def test_already_unsubscribed_is_idempotent(self, client):
        client.post("/api/v1/subscribers", json={"email": "twice@example.com"})
        token = make_unsubscribe_token("twice@example.com")
        client.get(f"/api/v1/subscribers/unsubscribe?email=twice@example.com&token={token}")
        r = client.get(f"/api/v1/subscribers/unsubscribe?email=twice@example.com&token={token}")
        assert r.json()["unsubscribed"] is True
        assert "Already" in r.json()["message"]

    def test_token_is_case_insensitive_on_email(self, client):
        client.post("/api/v1/subscribers", json={"email": "Case@Example.COM"})
        token = make_unsubscribe_token("Case@Example.COM")
        r = client.get(f"/api/v1/subscribers/unsubscribe?email=case@example.com&token={token}")
        assert r.json()["unsubscribed"] is True


class TestLegacyReminderSubscribe:
    """POST /api/v1/meta/reminder-subscribe now stores in the database."""

    def test_legacy_endpoint_still_works(self, client, db_session):
        r = client.post("/api/v1/meta/reminder-subscribe", json={"email": "legacy@example.com"})
        assert r.status_code == 200
        assert r.json()["subscribed"] is True
        from app.models.subscriber import Subscriber
        assert db_session.query(Subscriber).filter_by(email="legacy@example.com").count() == 1


def test_every_source_the_site_sends_is_one_the_api_takes():
    """Read off the frontend, so a page added with its own source cannot drift."""
    src = Path(__file__).resolve().parents[2] / "frontend" / "src"
    sources = {
        m.group(1)
        for path in src.rglob("*.jsx")
        if ".test." not in path.name
        for m in re.finditer(r'<EmailCapture\b[^>]*?\ssource="([^"]+)"', path.read_text(), re.S)
    }
    assert len(sources) > 30
    refused = []
    for source in sorted(sources):
        try:
            SubscriberRequest(email="x@example.com", source=source)
        except ValueError:
            refused.append(source)
    assert refused == []
