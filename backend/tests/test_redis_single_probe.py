"""One connect attempt per cooldown, however many requests arrive at once.

``get_redis`` runs on every request (the rate limiter calls it) and promised
"at most one connect per cooldown while the server is down". Nothing enforced
it across threads: when the cooldown ran out, every request thread in flight
passed the check together and each opened its own connection, so a Redis that
was black-holed stalled all of them for the connect timeout instead of one.
And when Redis came back, each built its own client and all but the last were
dropped unclosed.
"""
from __future__ import annotations

import threading
import time

from app.core import redis_client
from app.core.redis_client import reset
from tests.test_redis_client import _FakeClient, _install_fake_redis


class _SlowClient(_FakeClient):
    """Pings like a connect that takes its time — a black-holed host."""

    def ping(self):
        time.sleep(0.4)
        return super().ping()


def _expire_cooldown():
    redis_client._client = None
    redis_client._down_until = redis_client._now() - 1


def _burst(n=10):
    results: list[object] = [None] * n
    waits: list[float] = [0.0] * n
    start = threading.Barrier(n)

    def call(i):
        start.wait()
        began = time.monotonic()
        results[i] = redis_client.get_redis()
        waits[i] = time.monotonic() - began

    threads = [threading.Thread(target=call, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, waits


def test_a_burst_after_the_cooldown_makes_one_connect_attempt(monkeypatch):
    reset()
    calls = _install_fake_redis(monkeypatch, _SlowClient())
    _expire_cooldown()

    results, waits = _burst()

    assert len(calls) == 1, f"{len(calls)} connect attempts for one cooldown"
    # One thread paid for the probe; the others did not queue behind it.
    assert sum(w > 0.3 for w in waits) == 1, waits
    # The probe succeeded, so the client is in place for the next request.
    assert redis_client._client is not None
    reset()


def test_after_the_probe_everyone_shares_one_client(monkeypatch):
    reset()
    _install_fake_redis(monkeypatch, _FakeClient())
    _expire_cooldown()
    first = redis_client.get_redis()
    results, _ = _burst()
    assert all(r is first for r in results)
    reset()
