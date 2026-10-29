"""A data error is not an outage.

Tripping the Redis breaker drops the shared client for the whole process for a
cooldown: rate limiting falls back to per-worker counters, metrics and job
health go dark. Every caller tripped it on *any* exception, so a malformed
value — a stale entry in the recent-lookups list, a ``WRONGTYPE``, a refused
write — was reported as Redis being down. For the recent-lookups list it fed
itself: while the breaker was open no new lookup could be written to rotate the
bad entry out, so the landing page tripped it again every cooldown.
"""
from __future__ import annotations

import json
import logging

import pytest
import redis

from app.core import redis_client
from app.core.redis_client import reset


@pytest.fixture(autouse=True)
def _reset_module_state():
    reset()
    yield
    reset()


class _Client:
    """The parts of a redis client the callers here use."""

    def __init__(self, *, lrange=None, error=None):
        self._lrange = lrange or []
        self._error = error
        self.pushed: list[str] = []

    def lrange(self, *_):
        if self._error:
            raise self._error
        return self._lrange

    def get(self, *_):
        if self._error:
            raise self._error
        return None

    def pipeline(self, **_):
        client = self

        class _Pipe:
            def __getattr__(self, name):
                def call(*args):
                    if name == "lpush":
                        client.pushed.append(args[1])
                    return self
                return call

            def execute(self):
                if client._error:
                    raise client._error
                return [1, True, True, 1]

        return _Pipe()

    def close(self):
        pass


def _install(client):
    redis_client._client = client


def _tripped() -> bool:
    return redis_client._client is None and redis_client._down_until > 0


class TestReportFailure:
    @pytest.mark.parametrize(
        "exc",
        [redis.exceptions.ConnectionError("gone"), redis.exceptions.TimeoutError("slow"),
         ConnectionRefusedError("refused"), TimeoutError("socket")],
    )
    def test_an_outage_trips_the_breaker(self, exc):
        _install(_Client())
        redis_client.report_failure(exc, "anything")
        assert _tripped()

    @pytest.mark.parametrize(
        "exc",
        [redis.exceptions.ResponseError("WRONGTYPE Operation against a key"),
         redis.exceptions.ResponseError("OOM command not allowed"),
         ValueError("invalid literal for int()"), json.JSONDecodeError("x", "doc", 0),
         TypeError("string indices must be integers")],
    )
    def test_a_data_error_keeps_the_client_and_says_what_it_was(self, exc, caplog):
        client = _Client()
        _install(client)
        with caplog.at_level(logging.ERROR, logger="app.core.redis_client"):
            redis_client.report_failure(exc, "recent lookups read")
        assert redis_client._client is client
        assert not _tripped()
        [line] = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert type(exc).__name__ in line.getMessage()
        assert "recent lookups read" in line.getMessage()


class TestRecentLookups:
    URL = "/api/v1/meta/recent-lookups"

    def test_one_bad_entry_is_skipped_and_the_rest_served(self, client):
        good = json.dumps({"gstin": "29AAGCB7383J1Z4", "state": "Karnataka", "valid": True})
        _install(_Client(lrange=["{not json", '"a bare string"', "null", good]))

        response = client.get(self.URL)

        assert response.status_code == 200
        lookups = response.json()["lookups"]
        assert len(lookups) == 1 and lookups[0]["state"] == "Karnataka"
        assert not _tripped(), "a bad list entry is not Redis being down"

    def test_a_real_outage_still_trips_and_answers_empty(self, client):
        _install(_Client(error=redis.exceptions.ConnectionError("gone")))
        response = client.get(self.URL)
        assert response.json() == {"lookups": []}
        assert _tripped()


class TestRateLimiter:
    def test_a_refused_write_does_not_take_redis_away_from_everyone(self, client):
        # Redis at maxmemory refuses INCR with an OOM ResponseError. That is a
        # reason to fall back for this request, not to drop the client.
        _install(_Client(error=redis.exceptions.ResponseError("OOM command not allowed")))
        response = client.get("/api/v1/meta/states")
        assert response.status_code == 200
        assert not _tripped()
