"""Subscriber email capture and unsubscribe endpoints."""
from __future__ import annotations

from app.routers.misc import make_unsubscribe_token


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

    def test_email_is_normalised_to_lowercase(self, client):
        client.post("/api/v1/subscribers", json={"email": "Upper@Example.COM"})
        r = client.post("/api/v1/subscribers", json={"email": "upper@example.com"})
        assert r.json()["new"] is False

    def test_invalid_email_is_rejected(self, client):
        r = client.post("/api/v1/subscribers", json={"email": "not-an-email"})
        assert r.status_code == 422

    def test_invalid_source_is_rejected(self, client):
        r = client.post("/api/v1/subscribers", json={"email": "s@x.com", "source": "evil"})
        assert r.status_code == 422

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
