"""Health and the public metadata endpoints."""
from __future__ import annotations

import os
from datetime import UTC

import pytest

from app.routers import misc
from tests.conftest import BUSINESS_GSTIN

# Root ignores the permission bits, so a 0o500 directory is still writable and
# the read-only case would assert the opposite of what it means.
not_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses directory permissions",
)


@pytest.fixture()
def dependencies(monkeypatch):
    """Drive each health dependency independently.

    The endpoints exist to distinguish one failure from another, so the tests
    have to be able to fail one at a time.
    """

    def configure(*, database=True, redis=True, ai=True, storage=True):
        result = (True, None) if database else (False, "OperationalError")
        monkeypatch.setattr(misc, "check_database", lambda _db: result)
        monkeypatch.setattr(misc, "redis_ping", lambda: redis)
        monkeypatch.setattr(misc, "is_configured", lambda: ai)
        volume = (True, None) if storage else (False, "ReadOnly")
        monkeypatch.setattr(misc, "check_upload_dir", lambda: volume)

    return configure


def test_health_reports_each_dependency(client):
    """A degraded model provider is not a dead API.

    The product still ingests invoices on heuristics alone, so a monitor has
    to be able to tell the two apart.
    """
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    # No key is set in the test environment.
    assert body["ai"] == "unconfigured"


class TestHealthGrades:
    """The `health` field is the one a monitor should alert on."""

    def test_everything_up_is_ok(self, client, dependencies):
        dependencies()
        body = client.get("/api/v1/health").json()

        assert body["health"] == "ok"
        assert body["checks"]["redis"]["status"] == "ok"
        assert body["checks"]["ai"]["status"] == "configured"
        assert body["checks"]["storage"]["status"] == "ok"

    @pytest.mark.parametrize(
        ("down", "kwargs"),
        [
            ("redis", {"redis": False}),
            ("the model provider", {"ai": False}),
            ("the upload volume", {"storage": False}),
        ],
    )
    def test_a_soft_dependency_degrades_without_failing(self, client, dependencies, down, kwargs):
        """200 while degraded, on purpose.

        Uploads still parse — inline without Redis, on heuristics without a
        model — so a 503 here would page someone at 3am over a free-tier rate
        limit while the product carried on working.
        """
        dependencies(**kwargs)
        response = client.get("/api/v1/health")

        assert response.status_code == 200, down
        assert response.json()["health"] == "degraded"

    def test_a_dead_database_is_unhealthy_and_503(self, client, dependencies):
        dependencies(database=False)
        response = client.get("/api/v1/health")

        assert response.status_code == 503
        body = response.json()
        assert body["health"] == "unhealthy"
        assert body["database"] == "unavailable"
        # The error type is named so the operator knows whether it is a refused
        # connection or an exhausted pool before opening a shell.
        assert body["checks"]["database"]["error"] == "OperationalError"

    def test_the_database_check_is_timed_and_the_pool_reported(self, client, dependencies):
        """"Is the API slow because the pool is exhausted" without a shell."""
        dependencies()
        database = client.get("/api/v1/health").json()["checks"]["database"]

        assert isinstance(database["latency_ms"], float)
        assert "type" in database["pool"]

    def test_an_unwritable_upload_volume_is_named_and_degrades(self, client, dependencies):
        """The disk is the fourth thing an upload needs, and the only one that
        was probed at boot and never again. A monitor watching this used to see
        ``ok`` for as long as the volume stayed full."""
        dependencies(storage=False)
        body = client.get("/api/v1/health").json()

        assert body["storage"] == "unavailable"
        assert body["health"] == "degraded"
        storage = body["checks"]["storage"]
        assert storage["status"] == "unavailable"
        assert storage["error"] == "ReadOnly"
        assert storage["required_for"] == ["invoice uploads"]
        assert isinstance(storage["latency_ms"], float)

    @not_root
    def test_a_volume_that_went_read_only_after_boot_is_seen_without_a_restart(
        self, client, monkeypatch, tmp_path
    ):
        """The point of checking on every call rather than once at startup."""
        from app.core.config import settings

        volume = tmp_path / "uploads"
        volume.mkdir()
        monkeypatch.setattr(settings, "upload_dir", str(volume))
        assert client.get("/api/v1/health").json()["checks"]["storage"]["status"] == "ok"

        volume.chmod(0o500)
        try:
            storage = client.get("/api/v1/health").json()["checks"]["storage"]
        finally:
            volume.chmod(0o700)

        assert storage["status"] == "unavailable"
        assert storage["error"] == "ReadOnly"
        assert storage["path"] == str(volume)

    def test_a_volume_that_cannot_be_created_names_the_reason(
        self, client, monkeypatch, tmp_path
    ):
        from app.core.config import settings

        blocker = tmp_path / "file-not-dir"
        blocker.write_bytes(b"")
        monkeypatch.setattr(settings, "upload_dir", str(blocker / "uploads"))

        storage = client.get("/api/v1/health").json()["checks"]["storage"]

        assert storage["status"] == "unavailable"
        # The class of the OSError, so "a file is where the directory should
        # be" reads differently from "permission denied on the parent".
        assert storage["error"] in {"NotADirectoryError", "FileExistsError"}

    def test_a_check_that_raises_is_reported_rather_than_500ing(self, client, monkeypatch):
        """A health endpoint that can itself crash tells a monitor nothing."""

        def boom(_db):
            raise RuntimeError("connection pool is closed")

        monkeypatch.setattr(misc, "check_database", boom)
        response = client.get("/api/v1/health")

        assert response.status_code == 503
        assert response.json()["checks"]["database"]["error"] == "RuntimeError"


class TestProbes:
    """Liveness and readiness answer different questions on purpose."""

    def test_liveness_never_touches_a_dependency(self, client, monkeypatch):
        """Otherwise a database blip restarts every pod at once, turning a
        recoverable outage into a fleet-wide cold start."""

        def fail(*_args, **_kwargs):
            raise AssertionError("liveness must not check the database")

        monkeypatch.setattr(misc, "check_database", fail)
        monkeypatch.setattr(misc, "redis_ping", fail)

        response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_readiness_passes_when_the_database_answers(self, client, dependencies):
        dependencies()
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert isinstance(body["database_latency_ms"], float)

    def test_readiness_fails_on_a_dead_database(self, client, dependencies):
        """An instance that cannot read invoices should leave the rotation."""
        dependencies(database=False)
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["error"] == "OperationalError"

    def test_readiness_tolerates_redis_being_down(self, client, dependencies):
        """Reported, but not disqualifying — uploads still parse inline."""
        dependencies(redis=False)
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["redis"] == "unavailable"


def test_root_points_at_the_docs(client):
    body = client.get("/").json()
    assert body["app"] == "DoAide GST"
    assert body["health"] == "/api/v1/health"


def test_states_are_listed(client):
    states = client.get("/api/v1/meta/states").json()
    assert states["27"] == "Maharashtra"
    assert states["29"] == "Karnataka"
    assert len(states) >= 36


def test_gstin_lookup_decodes_a_valid_gstin(client):
    body = client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN}").json()
    assert body["valid"] is True
    assert body["state_name"] == "Maharashtra"
    assert body["pan"] == "AAPFU0939F"


def test_gstin_lookup_explains_an_invalid_one(client):
    """A 200 with ``valid: false``, not an error.

    The sign-up form calls this on every keystroke; a 4xx per character would
    be indistinguishable from the endpoint being broken.
    """
    body = client.get("/api/v1/meta/gstin/27AAPFU0939F1ZW").json()
    assert body["valid"] is False
    assert "check digit" in body["error"].lower()


def test_gstin_lookup_needs_no_authentication(client):
    assert client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN}").status_code == 200


class TestTheGstinLookupDoesNotEchoUnboundedInput:
    """The only route that reflects its path segment to an anonymous caller.

    An unparseable input is answered with ``normalize(gstin)`` so the sign-up
    form can show what was read. Unbounded, that made a 20KB path segment a
    20KB response body — work and bandwidth before any account exists, behind
    nothing but an IP-keyed limit.
    """

    def test_an_input_no_gstin_could_be_is_refused(self, client):
        response = client.get("/api/v1/meta/gstin/" + "A" * 20_000)
        assert response.status_code == 422

    def test_the_refusal_does_not_echo_the_input_back(self, client):
        """The point of the bound. A 4xx that still reflected 20KB would have
        moved the response code and left the behaviour."""
        response = client.get("/api/v1/meta/gstin/" + "A" * 20_000)
        assert len(response.content) < 2_000

    def test_a_gstin_pasted_with_separators_is_still_read(self, client):
        """The bound has to clear what people actually paste out of a PDF.

        ``normalize`` strips the spaces and hyphens, so this is the same GSTIN
        as the valid one above — it must not be refused for being longer than
        fifteen characters.
        """
        body = client.get("/api/v1/meta/gstin/27 AAPFU0939F 1ZV").json()
        assert body["valid"] is True
        assert body["gstin"] == BUSINESS_GSTIN

    def test_the_keystroke_contract_still_holds(self, client):
        """Every prefix a person types on the way to a full GSTIN stays a 200.

        This is the contract the route documents and the reason it does not
        answer 4xx for an invalid GSTIN. The bound is only allowed to catch
        input that is not a GSTIN at all, so nothing on this path may move.
        """
        for length in range(1, len(BUSINESS_GSTIN) + 1):
            response = client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN[:length]}")
            assert response.status_code == 200, BUSINESS_GSTIN[:length]


class TestRecentLookups:
    """Server-side recent GSTIN lookups — public, backed by Redis."""

    def test_recent_lookups_returns_empty_without_redis(self, client, monkeypatch):
        monkeypatch.setattr(misc, "get_redis", lambda: None)
        response = client.get("/api/v1/meta/recent-lookups")
        assert response.status_code == 200
        assert response.json()["lookups"] == []

    def test_valid_lookup_is_recorded_and_returned(self, client, monkeypatch):
        recorded = []

        class FakeRedis:
            def pipeline(self, **_kw):
                return self

            def lrem(self, key, count, value):
                recorded.append(("lrem", key, value))

            def lpush(self, key, value):
                recorded.append(("lpush", key, value))

            def ltrim(self, key, start, end):
                recorded.append(("ltrim", key, start, end))

            def incr(self, key):
                recorded.append(("incr", key))

            def execute(self):
                pass

            def lrange(self, key, start, end):
                import json
                return [json.dumps({
                    "gstin": BUSINESS_GSTIN,
                    "state_name": "Maharashtra",
                    "valid": True,
                })]

        monkeypatch.setattr(misc, "get_redis", lambda: FakeRedis())
        client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN}")
        assert any(op[0] == "lpush" for op in recorded)
        # The same pipeline feeds the /meta/stats counter: a lookup that is
        # worth listing is a lookup that is worth counting.
        assert ("incr", misc._LOOKUP_COUNT_KEY) in recorded

        response = client.get("/api/v1/meta/recent-lookups")
        assert response.status_code == 200
        lookups = response.json()["lookups"]
        assert len(lookups) == 1
        assert lookups[0]["gstin"] == misc._masked_gstin(BUSINESS_GSTIN)

    def test_the_public_feed_never_shows_whose_gstin_was_looked_up(
        self, client, monkeypatch
    ):
        """Neither what is stored nor what is served — including an entry
        stored before masking — carries the PAN inside the GSTIN."""
        import json

        stored = []

        class FakeRedis:
            def pipeline(self, **_kw):
                return self

            def lrem(self, key, count, value):
                pass

            def lpush(self, key, value):
                stored.append(value)

            def ltrim(self, key, start, end):
                pass

            def incr(self, key):
                pass

            def execute(self):
                pass

            def lrange(self, key, start, end):
                legacy = json.dumps(
                    {"gstin": BUSINESS_GSTIN, "state_name": "Maharashtra", "valid": True}
                )
                return [*stored, legacy]

        monkeypatch.setattr(misc, "get_redis", lambda: FakeRedis())
        client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN}")
        pan = BUSINESS_GSTIN[2:12]
        assert stored and all(pan not in entry for entry in stored)

        lookups = client.get("/api/v1/meta/recent-lookups").json()["lookups"]
        assert len(lookups) == 2
        for lookup in lookups:
            assert pan not in lookup["gstin"]
            assert lookup["gstin"] == BUSINESS_GSTIN[:2] + "•" * 10 + BUSINESS_GSTIN[12:]

    def test_a_malformed_stored_gstin_is_hidden_whole(self):
        assert misc._masked_gstin("27AAPFU") == "•" * 7

    def test_invalid_gstin_is_not_recorded(self, client, monkeypatch):
        recorded = []

        class FakeRedis:
            def pipeline(self, **_kw):
                return self

            def lrem(self, key, count, value):
                recorded.append(("lrem", key, value))

            def lpush(self, key, value):
                recorded.append(("lpush", key, value))

            def ltrim(self, key, start, end):
                recorded.append(("ltrim", key, start, end))

            def incr(self, key):
                recorded.append(("incr", key))

            def execute(self):
                pass

        monkeypatch.setattr(misc, "get_redis", lambda: FakeRedis())
        client.get("/api/v1/meta/gstin/27AAPFU0939F1ZW")
        assert len(recorded) == 0

    def test_no_auth_required(self, client, monkeypatch):
        monkeypatch.setattr(misc, "get_redis", lambda: None)
        response = client.get("/api/v1/meta/recent-lookups")
        assert response.status_code == 200


class TestUsageStats:
    """Aggregate usage counts for public social proof — real rows, never invented."""

    @pytest.fixture(autouse=True)
    def fresh_cache(self):
        # The endpoint remembers its answer per process, so a figure computed
        # under one test must not become the next test's assertion.
        misc._stats_cache = None
        yield
        misc._stats_cache = None

    def test_an_empty_database_without_redis_reports_zeroes(self, client, monkeypatch):
        monkeypatch.setattr(misc, "get_redis", lambda: None)
        response = client.get("/api/v1/meta/stats")
        assert response.status_code == 200
        assert response.json() == {"businesses": 0, "invoices": 0, "gstin_lookups": 0}

    def test_live_businesses_and_invoices_are_counted(
        self, client, db_session, business, monkeypatch
    ):
        from datetime import date
        from decimal import Decimal

        from app.models.invoice import Invoice, InvoiceStatus, InvoiceType

        monkeypatch.setattr(misc, "get_redis", lambda: None)
        for n in (1, 2):
            db_session.add(Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PARSED,
                counterparty_gstin="29AABCU9603R1ZM",
                invoice_number=f"ST-{n}",
                invoice_date=date(2026, 9, n),
                period="2026-09",
                taxable_value=Decimal("100.00"),
                cgst=Decimal("9.00"),
                sgst=Decimal("9.00"),
                igst=Decimal("0.00"),
                cess=Decimal("0.00"),
                total_value=Decimal("118.00"),
            ))
        db_session.commit()

        body = client.get("/api/v1/meta/stats").json()
        assert body["businesses"] == 1
        assert body["invoices"] == 2

    def test_soft_deleted_rows_are_not_usage(self, client, db_session, business, monkeypatch):
        from datetime import datetime

        monkeypatch.setattr(misc, "get_redis", lambda: None)
        business.deleted_at = datetime.now(UTC)
        db_session.commit()

        body = client.get("/api/v1/meta/stats").json()
        assert body["businesses"] == 0

    def test_the_lookup_counter_is_read_from_redis(self, client, monkeypatch):
        class FakeRedis:
            def get(self, key):
                assert key == misc._LOOKUP_COUNT_KEY
                return b"1234"

        monkeypatch.setattr(misc, "get_redis", lambda: FakeRedis())
        assert client.get("/api/v1/meta/stats").json()["gstin_lookups"] == 1234

    def test_a_failing_redis_degrades_to_zero_lookups(self, client, monkeypatch):
        class FakeRedis:
            def get(self, key):
                raise ConnectionError("down")

        monkeypatch.setattr(misc, "get_redis", lambda: FakeRedis())
        response = client.get("/api/v1/meta/stats")
        assert response.status_code == 200
        assert response.json()["gstin_lookups"] == 0

    def test_the_answer_is_cached_until_the_ttl_lapses(
        self, client, db_session, business, monkeypatch
    ):
        monkeypatch.setattr(misc, "get_redis", lambda: None)
        assert client.get("/api/v1/meta/stats").json()["businesses"] == 1

        from datetime import datetime

        business.deleted_at = datetime.now(UTC)
        db_session.commit()

        # Within the TTL the stale figure is the answer — that staleness is
        # the point of the cache, and a minute of it is invisible on counts
        # that only ever grow.
        assert client.get("/api/v1/meta/stats").json()["businesses"] == 1

        monkeypatch.setattr(misc, "_STATS_TTL_SECONDS", 0.0)
        assert client.get("/api/v1/meta/stats").json()["businesses"] == 0

    def test_no_auth_required(self, client, monkeypatch):
        monkeypatch.setattr(misc, "get_redis", lambda: None)
        assert client.get("/api/v1/meta/stats").status_code == 200


class TestReminderSubscribe:
    """Email capture for GST filing deadline reminders — public, no auth."""

    def test_a_valid_email_is_accepted(self, client):
        response = client.post(
            "/api/v1/meta/reminder-subscribe",
            json={"email": "user@example.com"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["subscribed"] is True
        assert "email" not in body

    def test_an_invalid_email_is_rejected(self, client):
        response = client.post(
            "/api/v1/meta/reminder-subscribe",
            json={"email": "not-an-email"},
        )
        assert response.status_code == 422

    def test_a_missing_email_is_rejected(self, client):
        response = client.post(
            "/api/v1/meta/reminder-subscribe",
            json={},
        )
        assert response.status_code == 422

    def test_no_auth_required(self, client):
        response = client.post(
            "/api/v1/meta/reminder-subscribe",
            json={"email": "anon@example.com"},
        )
        assert response.status_code == 200

    def test_email_not_logged_as_pii(self, client, caplog):
        """The subscriber's email must not appear in log output."""
        import logging

        with caplog.at_level(logging.DEBUG):
            client.post(
                "/api/v1/meta/reminder-subscribe",
                json={"email": "secret-pii@example.com"},
            )
        for record in caplog.records:
            assert "secret-pii@example.com" not in record.getMessage()


class TestHealthAnswersHead:
    """P16 M7: uptime monitors and load balancers commonly probe with HEAD, and
    the health routes were GET-only — a 405 that reads as "down" while the API
    serves. HEAD answers with the status GET would, and no body."""

    @pytest.mark.parametrize(
        "path", ["/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"]
    )
    def test_head_is_200_when_healthy(self, client, dependencies, path):
        dependencies()
        response = client.head(path)
        assert response.status_code == 200
        assert response.content == b""

    @pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/health/ready"])
    def test_head_carries_the_503_too(self, client, dependencies, path):
        dependencies(database=False)
        assert client.head(path).status_code == client.get(path).status_code == 503
