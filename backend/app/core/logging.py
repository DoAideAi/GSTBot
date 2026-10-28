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
import re
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

# Redacting by key misses a value that travels somewhere else — and a GSTIN
# travels in URL paths: /meta/gstin/{gstin} and /gpt/gstin/{gstin} are public
# lookups of anyone's registration, so the access line, every "Request
# rejected" line and uvicorn's own access log all carried a third party's
# GSTIN. Characters 3-12 of a GSTIN are a PAN, which ``pan`` above already
# says may not be logged. So the formatted line itself is masked, whichever
# key, message or traceback the identifier arrived in.
#
# A GSTIN keeps its state code and last three characters, which is enough to
# tell two lines apart and identifies nobody. A bare PAN is masked whole; its
# fourth character is the holder type, which keeps the pattern from matching
# the random ids (correlation, Razorpay) that share its alphabet.
_GSTIN_RE = re.compile(r"\b(\d{2})[A-Z]{5}\d{4}[A-Z]([1-9A-Z]Z[0-9A-Z])\b", re.IGNORECASE)
_PAN_RE = re.compile(r"\b[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]\b")


def mask_identifiers(text: str) -> str:
    """*text* with every GSTIN's PAN and every bare PAN masked."""
    text = _GSTIN_RE.sub(lambda m: f"{m.group(1)}{'*' * 10}{m.group(2)}", text)
    return _PAN_RE.sub("*" * 10, text)


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


class AccessQueryFilter(logging.Filter):
    """Drop the query string from uvicorn's access lines.

    uvicorn logs ``full_path``, query included, and some of our URLs carry a
    credential there: the unsubscribe link's token, Meta's
    ``hub.verify_token`` and the OAuth callback's ``code`` and ``state``. A
    key-based redaction cannot see inside a formatted path, so the query goes
    entirely — the app's own access line already logs the path alone.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.name != "uvicorn.access" or not isinstance(args, tuple) or len(args) < 3:
            return True
        path = args[2]
        if isinstance(path, str) and "?" in path:
            record.args = (*args[:2], path.split("?", 1)[0], *args[3:])
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

        return mask_identifiers(json.dumps(payload, default=str, ensure_ascii=False))


class ConsoleFormatter(logging.Formatter):
    """Human-readable, with the correlation id kept in front of the message."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        return mask_identifiers(super().format(record))


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
    handler.addFilter(AccessQueryFilter())

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
