"""SQLAlchemy engine, session factory, and declarative base.

Uses SQLAlchemy 2.0 style. The engine URL comes from settings, so tests can
override it with an in-memory SQLite database.

The pool is configured rather than left at its defaults, because the defaults
are wrong in both directions for this workload. A GST filing run is bursty —
one business exports a period and fires a dozen queries at once — so the pool
needs overflow; and the API runs behind several worker processes against a
stock Postgres, so ``pool_size`` has to be small enough that the processes
together stay under ``max_connections``.
"""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.sanitize import encodable, json_finite, without_nul

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(url: str) -> dict:
    """Engine options appropriate to the backend behind *url*."""
    common: dict = {
        # Every checkout is validated with a one-round-trip ping. Cheap next to
        # a request failing because a pooler recycled the socket underneath it.
        "pool_pre_ping": True,
        "future": True,
        "echo": settings.db_echo,
        # Keep the bound values out of every exception's message. SQLAlchemy
        # appends ``[parameters: ...]`` to the text, and each handler and task
        # logs these exceptions with their traceback, so a conflicting insert
        # into ``users`` wrote the email and the password hash to the journal.
        # The logging module redacts those keys, but it can't see inside a
        # formatted message. The statement itself is kept. Echo is the
        # exception: someone who turned it on locally wants to see the values.
        "hide_parameters": not settings.db_echo,
    }

    if url.startswith("sqlite"):
        # SQLite has no pooling story worth configuring. An in-memory database
        # additionally needs StaticPool, or every connection opens its own
        # fresh, empty database.
        sqlite_args = {"check_same_thread": False}
        if ":memory:" in url or "mode=memory" in url:
            return {**common, "connect_args": sqlite_args, "poolclass": StaticPool}
        return {**common, "connect_args": sqlite_args}

    connect_args: dict = {
        # Fail fast when the server is unreachable rather than hanging the
        # worker that tried to reach it.
        "connect_timeout": 10,
        # Names the process in pg_stat_activity, which is what turns "some
        # connection is holding a lock" into an answerable question.
        "application_name": f"{settings.app_name.lower()}-{settings.environment}",
    }
    if settings.db_statement_timeout_seconds:
        connect_args["options"] = (
            f"-c statement_timeout={settings.db_statement_timeout_seconds * 1000}"
        )

    return {
        **common,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
        "connect_args": connect_args,
    }


def _make_engine(url: str) -> Engine:
    new_engine = create_engine(url, **_engine_kwargs(url))

    if url.startswith("sqlite"):

        @event.listens_for(new_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            # SQLite ignores foreign keys unless asked, which would let the
            # suite pass against a schema Postgres would reject.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return new_engine


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@event.listens_for(Session, "before_flush")
def _strip_nul_before_flush(session: Session, _flush_context, _instances) -> None:
    """Remove U+0000 from every string and JSON value about to be written.

    PostgreSQL refuses NUL in a text column and inside JSON, so one in any
    value is a failed flush — a 500, on whatever route was writing. SQLite
    stores it, so the suite never sees the failure. Values reach the database
    from forms, uploaded documents, imported GSTR-2B files, the public
    feedback widget and the parser, and guarding each schema is a list that
    the next field falls off. Every ORM write passes through here instead.

    Only NUL, and only the values that contain one: anything else a field
    should not hold is its schema's to refuse, with a message.

    JSON values also lose NaN and ±Infinity (see ``json_finite``), and every
    value loses unpaired UTF-16 surrogates (see ``encodable``): the other two
    things Postgres refuses — a surrogate cannot be encoded to UTF-8 at all, and
    escaped inside JSON it is "Unicode low surrogate must follow a high
    surrogate". pypdf can hand one back from a PDF string with a broken pair.
    Compared by ``repr`` because ``nan != nan`` would make every value holding
    one look changed — harmless here, but the comparison should say what it
    means.
    """
    for obj in (*session.new, *session.dirty):
        state = inspect(obj)
        for attr in state.mapper.column_attrs:
            value = state.dict.get(attr.key)
            if isinstance(value, (str, dict, list)):
                cleaned = encodable(without_nul(value))
                if isinstance(cleaned, (dict, list)):
                    cleaned = json_finite(cleaned)
                if repr(cleaned) != repr(value):
                    setattr(obj, attr.key, cleaned)


def _param_without_nul(value):
    return value.replace("\x00", "") if isinstance(value, str) and "\x00" in value else value


def without_nul_params(parameters):
    """Bound parameters with NUL removed from every string, in any DBAPI shape.

    The read-side half of ``_strip_nul_before_flush``. psycopg refuses to send a
    string holding U+0000 at all — "PostgreSQL text fields cannot contain NUL"
    — so a NUL in anything a query compares against was a ``DataError`` and a
    500: the password sign-in, whose ``username`` is a form field matched
    against ``users.email`` before anything validates it, on a public route.
    No stored value can hold one (the flush hook sees to that), so removing it
    finds exactly what the stored data could ever have matched.
    """
    if isinstance(parameters, dict):
        return {key: _param_without_nul(value) for key, value in parameters.items()}
    if isinstance(parameters, tuple):
        return tuple(_param_without_nul(value) for value in parameters)
    if isinstance(parameters, list):
        # executemany's list of per-row sets, or one statement's positional
        # values: a driver may use either.
        return [
            without_nul_params(item) if isinstance(item, dict | tuple | list)
            else _param_without_nul(item)
            for item in parameters
        ]
    return parameters


@event.listens_for(Engine, "before_cursor_execute", retval=True)
def _strip_nul_from_parameters(_conn, _cursor, statement, parameters, _context, _executemany):
    return statement, without_nul_params(parameters)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped DB session.

    Rolls back on the way out of a failed request. Without that, a session
    returned to the pool mid-transaction hands the next request a connection
    with an open, aborted transaction on it — and every statement after that
    fails with "current transaction is aborted" until the process restarts.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database(session: Session | None = None) -> tuple[bool, str | None]:
    """``(reachable, error_type)`` — used by the health endpoint.

    Takes an optional session so the health route can reuse the request's own,
    which makes the check cover the pool the API actually serves from rather
    than a fresh connection that proves nothing about it.
    """
    try:
        if session is not None:
            session.execute(text("SELECT 1"))
        else:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001 - the caller's job is to report this
        logger.warning("Database health check failed: %s", exc)
        return False, type(exc).__name__


def pool_status() -> dict[str, int | str]:
    """Live pool counters, for the readiness endpoint.

    Answers "is the API slow because the pool is exhausted" without needing a
    shell on the container.
    """
    pool = engine.pool
    status: dict[str, int | str] = {"type": type(pool).__name__}
    for name, attr in (
        ("size", "size"),
        ("checked_in", "checkedin"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        getter = getattr(pool, attr, None)
        if not callable(getter):
            continue
        try:
            status[name] = int(getter())  # type: ignore[call-overload]
        except Exception as exc:  # noqa: BLE001 - a counter must not break health
            logger.debug("Pool counter %r unavailable: %s", name, exc)
            continue
    return status
