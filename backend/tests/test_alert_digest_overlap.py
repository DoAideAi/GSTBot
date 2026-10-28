"""Two digest runs at once.

The send task is acks_late, so a redelivery, a retry or a run started by hand
can overlap one in progress. Both read the pending alerts before either
stamps them, and each emailed the same digest. A run now takes a try-lock
first and stands down if another run holds it.

SQLite has no advisory locks, so the lock's two outcomes are staged directly,
and its Postgres statements are checked against a stand-in connection.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.alert import AlertStatus
from app.models.business import Business
from app.services import alert_delivery
from app.services.alert_delivery import send_pending_alerts
from tests.test_alert_delivery import make_alert, make_business, make_user


@pytest.fixture(autouse=True)
def _email_enabled(monkeypatch):
    monkeypatch.setattr(settings, "alerts_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")


@pytest.fixture()
def sent(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(alert_delivery, "send_email", lambda **kw: calls.append(kw))
    return calls


@pytest.fixture()
def business(db_session) -> Business:
    return make_business(db_session)


def _lock_held_elsewhere(monkeypatch):
    @contextmanager
    def held(db):
        yield False

    monkeypatch.setattr(alert_delivery, "_sole_run", held)


class TestWhileAnotherRunIsSending:
    def test_nothing_is_emailed(self, monkeypatch, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business)
        _lock_held_elsewhere(monkeypatch)

        result = send_pending_alerts(db_session)

        assert sent == []
        assert result.alerts_sent == 0

    def test_the_alerts_are_left_for_the_run_that_holds_the_lock(
        self, monkeypatch, db_session, business, sent
    ):
        make_user(db_session, business)
        alert = make_alert(db_session, business)
        _lock_held_elsewhere(monkeypatch)

        send_pending_alerts(db_session)

        db_session.refresh(alert)
        assert alert.status is AlertStatus.PENDING


class TestTheLock:
    def test_a_sole_run_sends(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business)

        assert send_pending_alerts(db_session).alerts_sent == 1

    def _postgres(self, acquired):
        executed = []

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def scalar(self, statement):
                executed.append(str(statement))
                return acquired

        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=Conn)
        return SimpleNamespace(get_bind=lambda: bind), executed

    def test_it_tries_rather_than_waits_and_unlocks_after(self):
        db, executed = self._postgres(True)

        with alert_delivery._sole_run(db) as alone:
            assert alone is True
            assert len(executed) == 1

        assert "pg_try_advisory_lock" in executed[0]
        assert "pg_advisory_unlock" in executed[1]

    def test_a_lock_it_did_not_get_is_not_released(self):
        db, executed = self._postgres(False)

        with alert_delivery._sole_run(db) as alone:
            assert alone is False

        assert len(executed) == 1
