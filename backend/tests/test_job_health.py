"""Background job monitoring: worker reachability, queue depth, job heartbeats.

The suite's Redis URL points at a Unix socket that cannot exist — see
``tests/test_redis_client.py`` — so the unreachable path is real here rather
than mocked, and only the reachable path needs a double.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest

from app.celery_app import celery_app
from app.core.redis_client import reset as reset_redis
from app.services import job_health


@pytest.fixture(autouse=True)
def _reset_redis_state():
    reset_redis()
    yield
    reset_redis()


class _FakeStore:
    """A dict-backed stand-in for the subset of the redis-py API used here."""

    def __init__(self, *, depth: int = 0):
        self.data: dict[str, str] = {}
        self.depth = depth

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def llen(self, key):
        return self.depth

    def ping(self):
        return True


def _install_fake_redis_module(monkeypatch, client):
    """Stand in for the ``redis`` package that ``queue_status`` imports inline."""
    module = type(sys)("redis")
    module.Redis = type("Redis", (), {"from_url": staticmethod(lambda url, **kw: client)})
    monkeypatch.setitem(sys.modules, "redis", module)


# ---------------------------------------------------------------------------
# Heartbeats
# ---------------------------------------------------------------------------

class TestHeartbeats:
    def test_recording_never_raises_when_redis_is_unreachable(self):
        # The suite's real, unreachable Redis. Must be silent.
        job_health.record_heartbeat("stalled-parse-sweep")

    def test_with_no_redis_every_job_is_unjudgeable(self):
        statuses = job_health.job_statuses()
        assert {s.name for s in statuses} == set(job_health.JOB_STALE_AFTER_SECONDS)
        assert all(s.last_run is None and s.stale is None for s in statuses)

    def test_a_fresh_heartbeat_is_not_stale(self, monkeypatch):
        store = _FakeStore()
        monkeypatch.setattr(job_health, "get_redis", lambda: store)

        job_health.record_heartbeat("stalled-parse-sweep")
        statuses = {s.name: s for s in job_health.job_statuses()}

        assert statuses["stalled-parse-sweep"].last_run is not None
        assert statuses["stalled-parse-sweep"].stale is False

    def test_an_old_heartbeat_is_stale(self, monkeypatch):
        store = _FakeStore()
        monkeypatch.setattr(job_health, "get_redis", lambda: store)

        stale_at = datetime.now(UTC) - timedelta(hours=100)
        job_health.record_heartbeat("filing-deadline-sweep", at=stale_at)
        statuses = {s.name: s for s in job_health.job_statuses()}

        assert statuses["filing-deadline-sweep"].stale is True

    def test_redis_up_but_never_run_is_reported_stale_not_unknown(self, monkeypatch):
        # Distinguishes "no way to check" (Redis down, stale=None) from "we
        # checked, and it has never once reported in" (stale=True).
        store = _FakeStore()
        monkeypatch.setattr(job_health, "get_redis", lambda: store)

        statuses = {s.name: s for s in job_health.job_statuses()}
        assert all(s.stale is True for s in statuses.values())


# ---------------------------------------------------------------------------
# Queue depth
# ---------------------------------------------------------------------------

class TestQueueStatus:
    def test_unreachable_broker_is_reported_not_raised(self):
        result = job_health.queue_status()
        assert result.reachable is False
        assert result.depth is None
        assert result.error

    def test_a_reachable_broker_reports_its_depth(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_broker_url", "redis://localhost:6379/1")
        store = _FakeStore(depth=7)
        _install_fake_redis_module(monkeypatch, store)

        result = job_health.queue_status()
        assert result.reachable is True
        assert result.depth == 7

    def test_a_non_redis_broker_is_reported_unreachable(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_broker_url", "amqp://localhost")
        result = job_health.queue_status()
        assert result.reachable is False
        assert "not Redis" in result.error

    def test_a_broker_that_refuses_the_connection_is_reported_not_raised(
        self, monkeypatch
    ):
        """The queue depth is one field of a health response, not the response.

        This runs inside ``/health/jobs``, which exists to be readable when
        things are broken. An unreachable broker is precisely the condition it
        is asked about, so the error becomes a field and the other checks — the
        heartbeats, the worker ping — still get to answer.
        """
        monkeypatch.setattr(
            job_health.settings, "celery_broker_url", "redis://localhost:6379/1"
        )

        class _Refusing:
            def llen(self, _queue):
                raise ConnectionError("Error 111 connecting to localhost:6379")

        _install_fake_redis_module(monkeypatch, _Refusing())

        result = job_health.queue_status()

        assert result.reachable is False
        assert result.depth is None
        # Typed, because "ConnectionError" and "TimeoutError" send an operator
        # to different places and the bare message often says neither.
        assert result.error == "ConnectionError"

    def test_the_brokers_message_goes_to_the_log_not_the_answer(self, monkeypatch, caplog):
        # ``/health/jobs`` is public, and a broker's message names the host
        # and port it could not reach. Same split as the database check.
        monkeypatch.setattr(
            job_health.settings, "celery_broker_url", "redis://localhost:6379/1"
        )

        class _Refusing:
            def llen(self, _queue):
                raise ConnectionError("Error 111 connecting to redis.internal:6380")

        _install_fake_redis_module(monkeypatch, _Refusing())

        with caplog.at_level("WARNING", logger="app.services.job_health"):
            result = job_health.queue_status()

        assert "redis.internal" not in result.error
        assert "redis.internal:6380" in caplog.text

    def test_a_broker_url_redis_cannot_parse_is_reported_not_raised(self, monkeypatch):
        # The failure lands on ``from_url`` rather than on the command, which
        # is a different line inside the same try. Both have to be caught.
        monkeypatch.setattr(
            job_health.settings, "celery_broker_url", "redis://:@@:notaport/x"
        )

        result = job_health.queue_status()

        assert result.reachable is False
        assert result.error


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class TestWorkerStatus:
    def test_celery_disabled_is_reported_unreachable(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_enabled", False)
        result = job_health.worker_status()
        assert result.reachable is False
        assert "CELERY_ENABLED" in result.error

    def test_no_worker_answering_is_unreachable_not_an_error(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_enabled", True)

        class _Inspect:
            def ping(self):
                return None

        monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=1.0: _Inspect())

        result = job_health.worker_status()
        assert result.reachable is False
        assert result.workers == []

    def test_a_failed_ping_is_typed_and_its_message_is_only_logged(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(job_health.settings, "celery_enabled", True)

        def _inspect(timeout=1.0):
            raise OSError("cannot reach amqp://guest@broker.internal:5672//")

        monkeypatch.setattr(celery_app.control, "inspect", _inspect)

        with caplog.at_level("WARNING", logger="app.services.job_health"):
            result = job_health.worker_status()

        assert result.reachable is False
        assert result.error == "OSError"
        assert "broker.internal" in caplog.text

    def test_a_replying_worker_is_named(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_enabled", True)

        class _Inspect:
            def ping(self):
                return {"celery@worker-2": {"ok": "pong"}, "celery@worker-1": {"ok": "pong"}}

        monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=1.0: _Inspect())

        result = job_health.worker_status()
        assert result.reachable is True
        assert result.workers == ["celery@worker-1", "celery@worker-2"]

    def test_an_inspect_failure_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_enabled", True)

        def _boom(timeout=1.0):
            raise RuntimeError("broker down")

        monkeypatch.setattr(celery_app.control, "inspect", _boom)

        result = job_health.worker_status()
        assert result.reachable is False
        assert result.error == "RuntimeError"


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------

class TestTheEndpoint:
    def test_it_is_public(self, client):
        # No Authorization header on this client at all.
        response = client.get("/api/v1/health/jobs")
        assert response.status_code == 200

    def test_an_unreachable_broker_answers_without_its_address(self, client, monkeypatch):
        monkeypatch.setattr(
            job_health.settings, "celery_broker_url", "redis://localhost:6379/1"
        )

        class _Refusing:
            def llen(self, _queue):
                raise ConnectionError("Error 111 connecting to redis.internal:6380")

        _install_fake_redis_module(monkeypatch, _Refusing())

        response = client.get("/api/v1/health/jobs")

        assert response.status_code == 200
        assert response.json()["queue"]["error"] == "ConnectionError"
        assert "redis.internal" not in response.text

    def test_it_reports_degraded_when_nothing_is_reachable(self, client):
        # The suite's real environment: no Redis, no broker, no worker.
        body = client.get("/api/v1/health/jobs").json()
        assert body["health"] == "degraded"
        assert body["workers"]["reachable"] is False
        assert body["queue"]["reachable"] is False
        assert len(body["jobs"]) == len(job_health.JOB_STALE_AFTER_SECONDS)

    def test_it_reports_ok_when_everything_is_healthy(self, client, monkeypatch):
        store = _FakeStore()
        for name in job_health.JOB_STALE_AFTER_SECONDS:
            store.set(job_health._HEARTBEAT_PREFIX + name, datetime.now(UTC).isoformat())
        monkeypatch.setattr(job_health, "get_redis", lambda: store)
        monkeypatch.setattr(job_health.settings, "celery_broker_url", "redis://localhost:6379/1")
        _install_fake_redis_module(monkeypatch, store)
        monkeypatch.setattr(job_health.settings, "celery_enabled", True)

        class _Inspect:
            def ping(self):
                return {"celery@worker-1": {"ok": "pong"}}

        monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=1.0: _Inspect())

        body = client.get("/api/v1/health/jobs").json()
        assert body["health"] == "ok"
        assert body["workers"]["names"] == ["celery@worker-1"]
        assert all(job["stale"] is False for job in body["jobs"])

    def test_celery_disabled_is_still_a_200(self, client, monkeypatch):
        monkeypatch.setattr(job_health.settings, "celery_enabled", False)
        response = client.get("/api/v1/health/jobs")
        assert response.status_code == 200
        assert response.json()["celery_enabled"] is False
