"""The engine, the request-scoped session, and the health counters.

This module is infrastructure, so almost none of it is reached by driving the
API: the suite runs on in-memory SQLite with ``get_db`` overridden, which means
the Postgres engine options, the session's rollback-on-failure, and the pool
counters are all code that ships without ever having run. Each is tested here
directly.

The Postgres options in particular can only be checked this way. Building the
kwargs is pure, but *using* them needs a server, so the assertions are on the
dict — which is the part that has been wrong before, and the part a deployment
depends on.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from app.core import database
from app.core.database import _engine_kwargs, check_database, get_db, pool_status

POSTGRES_URL = "postgresql+psycopg://gstbot:gstbot@db:5432/gstbot"


class TestEngineOptionsMatchTheBackend:
    """One URL scheme must not get the other's options."""

    def test_an_in_memory_sqlite_url_gets_a_static_pool(self):
        # Without StaticPool every connection opens its own blank database and
        # the suite's fixtures vanish between statements.
        kwargs = _engine_kwargs("sqlite+pysqlite:///:memory:")
        assert kwargs["poolclass"] is StaticPool

    def test_the_shared_cache_spelling_of_in_memory_is_recognised_too(self):
        kwargs = _engine_kwargs("sqlite+pysqlite:///file:x?mode=memory&cache=shared")
        assert kwargs["poolclass"] is StaticPool

    def test_a_sqlite_file_is_left_on_the_default_pool(self):
        # A file-backed database survives reconnection on its own, so pinning
        # it to one connection would only serialise the suite.
        kwargs = _engine_kwargs("sqlite+pysqlite:///./gstbot.db")
        assert "poolclass" not in kwargs

    def test_sqlite_allows_use_across_threads(self):
        # TestClient runs the app on a worker thread; the default check would
        # reject the session opened on it.
        kwargs = _engine_kwargs("sqlite+pysqlite:///:memory:")
        assert kwargs["connect_args"]["check_same_thread"] is False

    def test_sqlite_is_not_given_postgres_connect_args(self):
        # connect_timeout and application_name are libpq options. Handing them
        # to pysqlite is a TypeError at connect time.
        kwargs = _engine_kwargs("sqlite+pysqlite:///:memory:")
        assert set(kwargs["connect_args"]) == {"check_same_thread"}

    def test_postgres_gets_the_configured_pool_sizing(self):
        kwargs = _engine_kwargs(POSTGRES_URL)
        from app.core.config import settings

        assert kwargs["pool_size"] == settings.db_pool_size
        assert kwargs["max_overflow"] == settings.db_max_overflow
        assert kwargs["pool_timeout"] == settings.db_pool_timeout
        assert kwargs["pool_recycle"] == settings.db_pool_recycle

    def test_postgres_fails_fast_rather_than_hanging_a_worker(self):
        assert _engine_kwargs(POSTGRES_URL)["connect_args"]["connect_timeout"] == 10

    def test_postgres_names_the_process_for_pg_stat_activity(self):
        # This is what turns "some connection holds a lock" into a question
        # with an answer, so the value must identify app *and* environment.
        from app.core.config import settings

        application_name = _engine_kwargs(POSTGRES_URL)["connect_args"]["application_name"]
        assert settings.app_name.lower() in application_name
        assert settings.environment in application_name

    def test_the_statement_timeout_is_sent_to_postgres_in_milliseconds(self, monkeypatch):
        # Postgres reads bare `statement_timeout` as ms. Passing seconds would
        # cancel a 30-second report after 30 milliseconds.
        monkeypatch.setattr(database.settings, "db_statement_timeout_seconds", 30)
        assert _engine_kwargs(POSTGRES_URL)["connect_args"]["options"] == (
            "-c statement_timeout=30000"
        )

    def test_no_statement_timeout_configured_sends_no_options_at_all(self, monkeypatch):
        monkeypatch.setattr(database.settings, "db_statement_timeout_seconds", 0)
        assert "options" not in _engine_kwargs(POSTGRES_URL)["connect_args"]

    def test_every_backend_validates_a_connection_before_handing_it_out(self):
        # A pooler recycling the socket underneath an idle connection is the
        # normal way a healthy deployment starts throwing OperationalError.
        for url in (POSTGRES_URL, "sqlite+pysqlite:///:memory:"):
            assert _engine_kwargs(url)["pool_pre_ping"] is True


class TestALoggedDatabaseErrorCarriesNoBoundValues:
    """P36 M2: every logged database error carried the row it was writing.

    SQLAlchemy puts ``[parameters: ...]`` in an exception's message, and every
    handler and task logs that exception with its traceback. A conflicting
    insert into ``users`` logged the email and the password hash beside it,
    both keys the log formatter promises never to write. A key-based redaction
    can't see inside a formatted message, so the engine has to leave the
    values out. The statement stays, and so does Postgres's own reason.
    """

    def test_an_integrity_error_does_not_quote_the_values(self):
        from sqlalchemy.exc import IntegrityError

        engine = database._make_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE people (email TEXT UNIQUE, hashed_password TEXT)")
            )
        row = {"email": "owner@example.com", "hashed_password": "$2b$12$secrethash"}
        with pytest.raises(IntegrityError) as caught, engine.begin() as connection:
            for _ in range(2):
                connection.execute(
                    text("INSERT INTO people VALUES (:email, :hashed_password)"), row
                )
        message = str(caught.value)
        assert "INSERT INTO people" in message
        assert "owner@example.com" not in message
        assert "secrethash" not in message

    def test_the_postgres_engine_hides_them_too(self):
        assert _engine_kwargs("postgresql+psycopg://u:p@db/gst")["hide_parameters"] is True


class _RecordingSession:
    """A session that records the calls ``get_db`` makes on the way out."""

    def __init__(self):
        self.calls: list[str] = []

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


class TestTheRequestScopedSession:
    def test_it_yields_a_session_that_can_run_a_query(self):
        generator = get_db()
        session = next(generator)
        try:
            assert session.execute(text("SELECT 1")).scalar() == 1
        finally:
            generator.close()

    def test_a_successful_request_closes_without_rolling_back(self, monkeypatch):
        recorder = _RecordingSession()
        monkeypatch.setattr(database, "SessionLocal", lambda: recorder)

        generator = get_db()
        next(generator)
        with pytest.raises(StopIteration):
            next(generator)

        assert recorder.calls == ["close"]

    def test_a_failed_request_rolls_back_before_closing(self, monkeypatch):
        # The regression this guards: a session returned to the pool with an
        # aborted transaction still open makes every later request on that
        # connection fail with "current transaction is aborted" until the
        # process restarts.
        recorder = _RecordingSession()
        monkeypatch.setattr(database, "SessionLocal", lambda: recorder)

        generator = get_db()
        next(generator)
        with pytest.raises(ValueError):
            generator.throw(ValueError("the route raised"))

        assert recorder.calls == ["rollback", "close"]

    def test_the_original_error_is_not_swallowed_by_the_rollback(self, monkeypatch):
        # A cleanup path that hides the cause turns every 500 into a mystery.
        monkeypatch.setattr(database, "SessionLocal", _RecordingSession)

        generator = get_db()
        next(generator)
        with pytest.raises(ValueError, match="the route raised"):
            generator.throw(ValueError("the route raised"))


class _BrokenSession:
    def execute(self, _statement):
        raise RuntimeError("connection reset by peer")


class TestTheDatabaseHealthCheck:
    def test_a_working_session_reports_reachable(self):
        generator = get_db()
        session = next(generator)
        try:
            assert check_database(session) == (True, None)
        finally:
            generator.close()

    def test_with_no_session_it_opens_its_own_connection(self):
        assert check_database() == (True, None)

    def test_a_broken_session_reports_the_error_type_not_the_message(self):
        # The type is safe to return to an unauthenticated health caller; the
        # message can carry a host, a port or a user name.
        reachable, error = check_database(_BrokenSession())
        assert reachable is False
        assert error == "RuntimeError"

    def test_it_never_raises_at_the_caller(self):
        # The health route has no handler for this; an exception here is a 500
        # on the endpoint whose job is to report failures.
        assert check_database(_BrokenSession())[0] is False


class _CountingPool:
    def size(self):
        return 5

    def checkedin(self):
        return 4

    def checkedout(self):
        return 1

    def overflow(self):
        return 0


class _PartialPool:
    """A pool whose counters are unavailable — as on SQLite's StaticPool."""

    def size(self):
        raise NotImplementedError("this pool does not count")

    # Not callable: some pools expose the attribute as a plain value.
    checkedin = 3


class TestThePoolCounters:
    def test_the_real_pool_reports_its_type(self):
        assert pool_status()["type"] == type(database.engine.pool).__name__

    def test_every_counter_is_reported_when_the_pool_has_them(self, monkeypatch):
        monkeypatch.setattr(database, "engine", SimpleNamespace(pool=_CountingPool()))
        assert pool_status() == {
            "type": "_CountingPool",
            "size": 5,
            "checked_in": 4,
            "checked_out": 1,
            "overflow": 0,
        }

    def test_a_counter_that_raises_is_skipped_rather_than_failing_health(self, monkeypatch):
        # Readiness must keep answering even on a pool that cannot introspect
        # itself, or a cosmetic gap takes the instance out of the load balancer.
        monkeypatch.setattr(database, "engine", SimpleNamespace(pool=_PartialPool()))
        status = pool_status()
        assert status == {"type": "_PartialPool"}

    def test_a_non_callable_counter_is_not_reported_as_a_number(self, monkeypatch):
        monkeypatch.setattr(database, "engine", SimpleNamespace(pool=_PartialPool()))
        assert "checked_in" not in pool_status()
