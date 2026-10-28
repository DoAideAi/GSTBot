"""Request metrics: counted per hour in Redis, read back by admins."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

import pytest

from app.core import metrics
from app.core.config import settings
from tests.conftest import TEST_EMAIL

URL = "/api/v1/health/metrics"


class FakeRedis:
    """The handful of hash commands metrics uses, in memory."""

    def __init__(self):
        self.hashes: dict[str, dict[str, float]] = defaultdict(dict)
        self.expiry: dict[str, int] = {}

    def pipeline(self, transaction=False):
        return _Pipe(self)

    def hincrby(self, key, field, n):
        self.hashes[key][field] = self.hashes[key].get(field, 0) + n

    def hincrbyfloat(self, key, field, n):
        self.hashes[key][field] = self.hashes[key].get(field, 0.0) + n

    def expire(self, key, seconds):
        self.expiry[key] = seconds

    def hgetall(self, key):
        return {k.encode(): str(v).encode() for k, v in self.hashes.get(key, {}).items()}


class _Pipe:
    def __init__(self, redis):
        self.redis, self.calls = redis, []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, a))

    def execute(self):
        return [getattr(self.redis, name)(*a) for name, a in self.calls]


@pytest.fixture()
def fake(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(metrics, "get_redis", lambda: redis)
    return redis


NOW = datetime(2026, 10, 28, 14, 30, tzinfo=UTC)


class TestCounting:
    def test_each_request_lands_in_its_hour_by_status_class(self, fake):
        for code, ms in [(200, 40), (201, 60), (404, 10), (500, 1500), (302, 5)]:
            metrics.record(code, ms, now=NOW)
        bucket = fake.hashes["gstbot:metrics:2026102814"]
        assert bucket["requests"] == 5
        assert (bucket["status_2xx"], bucket["status_3xx"]) == (2, 1)
        assert (bucket["status_4xx"], bucket["status_5xx"]) == (1, 1)
        assert bucket["slow"] == 1
        assert bucket["latency_ms_sum"] == 1615
        assert fake.expiry["gstbot:metrics:2026102814"] == 48 * 3600

    def test_the_summary_reports_rates_and_averages(self, fake):
        for code, ms in [(200, 100), (200, 100), (500, 400), (200, 200)]:
            metrics.record(code, ms, now=NOW)
        metrics.record(200, 50, now=datetime(2026, 10, 28, 13, 5, tzinfo=UTC))

        body = metrics.summary(2, now=NOW)
        assert [h["hour"] for h in body["hours"]] == ["2026-10-28T13:00Z", "2026-10-28T14:00Z"]
        assert body["hours"][1] == {
            "hour": "2026-10-28T14:00Z",
            "requests": 4,
            "status_2xx": 3,
            "status_3xx": 0,
            "status_4xx": 0,
            "status_5xx": 1,
            "slow": 0,
            "error_rate": 0.25,
            "avg_ms": 200.0,
        }
        assert body["totals"]["requests"] == 5
        assert body["totals"]["avg_ms"] == 170.0

    def test_an_empty_hour_is_zeros_not_a_division_by_zero(self, fake):
        assert metrics.summary(1, now=NOW)["totals"] == {
            "requests": 0, "status_4xx": 0, "status_5xx": 0, "slow": 0,
            "error_rate": 0.0, "avg_ms": 0.0,
        }

    def test_without_redis_nothing_is_recorded_and_nothing_raises(self, monkeypatch):
        monkeypatch.setattr(metrics, "get_redis", lambda: None)
        metrics.record(200, 10)
        assert metrics.summary() is None

    def test_a_failing_redis_never_fails_the_request(self, monkeypatch):
        class Broken:
            def pipeline(self, transaction=False):
                raise ConnectionError("gone")

        monkeypatch.setattr(metrics, "get_redis", lambda: Broken())
        metrics.record(200, 10)  # does not raise


class TestTheMiddlewareCounts:
    def test_real_requests_are_counted_and_health_probes_are_not(self, client, fake):
        client.get("/api/v1/health/live")
        client.get("/api/v1/meta/states")
        client.get("/api/v1/no-such-route")
        totals = metrics.summary(1)["totals"]
        assert totals["requests"] == 2
        assert totals["status_4xx"] == 1


class TestTheEndpoint:
    def test_admins_read_it(self, auth_client, fake, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", TEST_EMAIL)
        body = auth_client.get(URL, params={"hours": 3}).json()
        assert len(body["hours"]) == 3
        assert "error_rate" in body["totals"]

    def test_a_visitor_is_asked_to_sign_in(self, client, fake):
        assert client.get(URL).status_code == 401

    def test_a_user_who_is_not_an_admin_is_refused(self, auth_client, fake, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", "ops@doaide.com")
        assert auth_client.get(URL).status_code == 403

    def test_without_redis_it_says_so(self, auth_client, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", TEST_EMAIL)
        monkeypatch.setattr(metrics, "get_redis", lambda: None)
        assert auth_client.get(URL).status_code == 503

    @pytest.mark.parametrize("hours", [0, 49])
    def test_the_window_is_bounded(self, auth_client, fake, monkeypatch, hours):
        monkeypatch.setattr(settings, "admin_emails", TEST_EMAIL)
        assert auth_client.get(URL, params={"hours": hours}).status_code == 422
