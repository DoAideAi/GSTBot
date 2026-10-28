"""Structured logging, and the correlation id that ties a request together.

Every log line carries the id of the request that produced it. That is the
whole point of this module: when a business reports "my April upload failed",
the support answer has to be findable, and an invoice parse touches the API,
a Celery worker and a model provider before it fails. One id, set once at the
edge and propagated into the worker, is what makes those three sets of lines a
single story.

The formatter is chosen by configuration rather than by environment sniffing:
``LOG_FORMAT=json`` for anything shipping to a log aggregator, ``console`` for
a terminal.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

# A ContextVar rather than a thread-local: FastAPI runs sync endpoints in a
# threadpool and async ones on the event loop, and only a ContextVar is correct
# under both.
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

# Attributes LogRecord always carries. Anything else on a record was put there
# by a caller's ``extra=`` and belongs in the structured output.
_STANDARD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

# Never let these reach a log line, whatever key they arrive under. Logs are
# read by more people than the database is.
_REDACTED_KEYS = frozenset(
    {
        "password", "passwd", "secret", "token", "access_token", "authorization",
        "api_key", "apikey", "jwt_secret", "openrouter_api_key", "hashed_password",
        "set-cookie", "cookie",
        "recipient", "email_address", "email",
        "phone", "pan", "signature",
    }
)
_REDACTED = "[redacted]"


def new_correlation_id() -> str:
    """A fresh id. Short enough to paste into a support ticket."""
    return uuid.uuid4().hex[:16]


def get_correlation_id() -> str:
    """The current request's id, or "" outside a request."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> object:
    """Bind *value* for this context, returning the token needed to reset it."""
    return _correlation_id.set(value)


def reset_correlation_id(token: object) -> None:
    _correlation_id.reset(token)  # type: ignore[arg-type]


def bind_correlation_id(value: str | None = None) -> str:
    """Bind an id (generating one when absent) and return it.

    Used by the Celery worker, which has no HTTP edge to inherit one from but
    is handed the originating request's id on the task payload.
    """
    resolved = sanitize_correlation_id(value) or new_correlation_id()
    _correlation_id.set(resolved)
    return resolved


def sanitize_correlation_id(value: str | None) -> str:
    """Accept a client-supplied id only if it is safe to echo into a log.

    The header is attacker-controlled: a newline in it would let a caller forge
    log lines, and an unbounded one would let them pad every line in the file.
    Anything outside a conservative character set is rejected outright rather
    than escaped, because a request id has no reason to contain anything else.
    """
    if not value:
        return ""
    candidate = value.strip()[:64]
    if not candidate:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    return candidate if all(ch in allowed for ch in candidate) else ""


class CorrelationIdFilter(logging.Filter):
    """Put ``correlation_id`` on every record so formatters can rely on it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "correlation_id", ""):
            record.correlation_id = get_correlation_id() or "-"
        return True


def _redact(key: str, value: Any) -> Any:
    return _REDACTED if key.lower() in _REDACTED_KEYS else value


def _jsonable(value: Any) -> Any:
    """Coerce to something ``json.dumps`` accepts, never raising."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(_redact(str(k), v)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with ``extra=`` fields promoted to top level."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key in payload or key.startswith("_"):
                continue
            payload[key] = _jsonable(_redact(key, value))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable, with the correlation id kept in front of the message."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Install the root handler. Idempotent — safe to call from every entrypoint.

    Replaces any handler already on root rather than adding to it: uvicorn and
    Celery both install their own, and two handlers means every line twice.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt.lower() == "json" else ConsoleFormatter())
    handler.addFilter(CorrelationIdFilter())

    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn's own loggers propagate to root once their handlers are dropped,
    # so access lines and errors come out in the configured format too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # SQLAlchemy logs every statement at INFO when echo is on; the engine is
    # configured with echo=False, and this keeps a stray echo from flooding.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
