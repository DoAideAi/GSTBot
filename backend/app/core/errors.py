"""One error shape for the whole API, and the handlers that produce it.

Every failure — a 404 raised by a route, a validation error raised before the
route ran, a constraint violation raised by Postgres, or a bug — leaves through
here and comes back looking the same:

    {
      "detail": "Invoice not found",          # what a human should be told
      "error": {"code": "not_found", "status": 404, ...},
      "correlation_id": "9f2c1a0b4e7d5a63"    # what to quote in a support ticket
    }

``detail`` is kept as the primary field on purpose. It is what FastAPI already
returns, what every existing client reads, and what the frontend's error
formatter understands; ``error`` and ``correlation_id`` are added beside it
rather than replacing it, so hardening the API did not break its consumers.

The other rule here: an unexpected exception is logged in full and answered
with a generic message. A stack trace, a failing SQL statement or a connection
string in an HTTP response is a gift to whoever is probing the service, and the
correlation id is what lets support find the real error without publishing it.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import get_correlation_id

logger = logging.getLogger(__name__)

# Machine-readable codes for the statuses the API actually returns. A client
# should branch on these rather than on the prose in ``detail``, which is
# written for people and may be reworded.
_CODES = {
    400: "bad_request",
    401: "unauthorized",
    402: "payment_required",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    504: "upstream_timeout",
}


def error_code(status_code: int) -> str:
    return _CODES.get(status_code, "error" if status_code < 500 else "internal_error")


def error_body(
    status_code: int,
    detail: Any,
    *,
    code: str | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The response body every handler in this module returns."""
    body: dict[str, Any] = {
        "detail": detail,
        "error": {
            "code": code or error_code(status_code),
            "status": status_code,
            # A string rendering of ``detail`` for the common case where a
            # client wants one line without type-checking the field.
            "message": detail if isinstance(detail, str) else _summarise(detail),
        },
        "correlation_id": get_correlation_id() or "-",
    }
    if fields:
        body["error"]["fields"] = fields
    return _encodable(body)


def _encodable(value: Any) -> Any:
    """*value* with every unpaired UTF-16 surrogate replaced by U+FFFD.

    JSON may spell ``"\\ud800"`` and Python parses it to a lone surrogate,
    which UTF-8 cannot encode. An error body quotes what the caller sent — the
    422's ``input``, a detail naming the period or file — and ``JSONResponse``
    encodes to UTF-8 on the way out, so one escaped half-pair in any string
    field turned the refusal of that field into a 500, on every route. Scrubbed
    here because every handler's body is built here; a valid pair is joined
    and kept, only the half that cannot be written is replaced.
    """
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
        return value
    if isinstance(value, dict):
        return {_encodable(key): _encodable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encodable(item) for item in value]
    return value


def _summarise(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    if isinstance(detail, list):
        return "; ".join(
            str(item.get("msg") if isinstance(item, dict) else item) for item in detail
        )
    return str(detail)


# How much of a rejected value is quoted back in a 422.
#
# Pydantic puts the offending value in each error's ``input``, and that field
# is what makes a validation error actionable — "we read '2026-13', which is
# not a month" beats "invalid period". So it is truncated rather than dropped.
#
# The ceiling exists because the value is the *caller's*, and echoing it whole
# turns any 422 into a reflector: a 20KB path segment came back as a 20KB
# response body on the one public route that takes a string, before any
# account exists. Long enough that a real field — a GSTIN, a period, an
# invoice number — is quoted in full and nobody notices this constant.
_MAX_ECHOED_INPUT = 200

_TRUNCATION_MARKER = "…[truncated]"


def _bounded(value: Any) -> Any:
    """*value* with anything longer than the ceiling above cut down.

    Only strings are shortened in place. A rejected *body* arrives as the whole
    parsed dict or list, which has no meaningful prefix, so an oversized one is
    replaced by a note of its type rather than a mangled fragment of itself.
    """
    if isinstance(value, str):
        if len(value) <= _MAX_ECHOED_INPUT:
            return value
        return value[:_MAX_ECHOED_INPUT] + _TRUNCATION_MARKER
    if isinstance(value, (dict, list, tuple, set)):
        if len(value) <= _MAX_ECHOED_INPUT:
            return value
        return f"<{type(value).__name__} of {len(value)} items{_TRUNCATION_MARKER}>"
    return value


# How long a whole ``HTTPException`` detail may be.
#
# The ceiling above bounds what pydantic quotes; this bounds what a *route*
# hands the handler, which until now was nothing. A detail is prose a person
# wrote, so it was trusted — but several are built around a value out of the
# request: a return type out of the path, an invoice number out of an uploaded
# statement. ``params.Slug`` bounds the first at the input. The second came
# out of a GSTR-2B file as a 100KB ``inum``, was quoted in the refusal, and
# left as a 200KB 422 — the file reflected twice, once in ``detail`` and once
# in ``message``, with a 15MB upload allowance behind it.
#
# Bounded here rather than at each ``detail=`` so the guarantee does not
# depend on every route remembering, and set well above any sentence a route
# actually writes — the longest is a few hundred characters — so nothing real
# is ever cut. What this cuts is a detail that is mostly the caller's own
# bytes, and by then it has stopped being a message.
_MAX_DETAIL_LENGTH = 2000


def _bounded_detail(detail: Any) -> Any:
    """*detail* with any string in it cut to :data:`_MAX_DETAIL_LENGTH`.

    Dicts and lists are walked one level, which is every shape a route here
    raises: a string, ``{"message": ..., "invoice_id": ...}``, or a list of
    lines. The keys are the route's own and are left alone.
    """
    if isinstance(detail, str):
        if len(detail) <= _MAX_DETAIL_LENGTH:
            return detail
        return detail[:_MAX_DETAIL_LENGTH] + _TRUNCATION_MARKER
    if isinstance(detail, dict):
        return {key: _bounded_detail(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [_bounded_detail(item) for item in detail]
    return detail


def _bounded_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """``exc.errors()`` with every echoed value bounded.

    Applied to the whole error dict rather than to ``input`` alone: ``msg``
    quotes the value too on some pydantic errors, and ``ctx`` carries whatever
    a custom validator put in its message.
    """
    bounded: list[dict[str, Any]] = []
    for error in exc.errors():
        entry = {key: _bounded(value) for key, value in error.items()}
        if "input" in entry:
            if _is_secret(error.get("loc", ())):
                entry["input"] = _REDACTED
            elif isinstance(entry["input"], dict):
                # A "missing" error quotes the whole body it looked in, so a
                # register call without its email still carried the password.
                entry["input"] = {
                    key: _REDACTED if _is_secret((key,)) else value
                    for key, value in entry["input"].items()
                }
        bounded.append(entry)
    return bounded


# Fields whose value is never quoted back, however short. The echo above is
# what makes a 422 actionable for a GSTIN or a period; for a password it put
# the one the user just typed — "hunter2", seven characters, one short — into
# the response body, where browser error trackers and proxy logs keep it. The
# caller knows what they typed; ``msg`` says what was wrong with it. Matched
# on any part of ``loc`` so a nested ``credentials.api_key`` counts too.
_SECRET_FIELD = re.compile(r"password|secret|token|otp|api_?key", re.IGNORECASE)
_REDACTED = "[redacted]"


def _is_secret(loc: Any) -> bool:
    return any(isinstance(part, str) and _SECRET_FIELD.search(part) for part in loc)


def _field_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Flatten pydantic's error list into ``{field, message, type}`` entries.

    ``loc`` is dropped of its first element ("body", "query", "path") only when
    something follows it, so a whole-body error still names where it came from.
    """
    fields: list[dict[str, Any]] = []
    for error in _bounded_errors(exc):
        location = [str(part) for part in error.get("loc", ())]
        name = ".".join(location[1:]) if len(location) > 1 else ".".join(location)
        fields.append(
            {
                "field": _bounded(name or "body"),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
        )
    return fields


def register_exception_handlers(app: FastAPI) -> None:
    """Install every handler on *app*. Called once from ``create_app``."""

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = _field_errors(exc)
        logger.info(
            "Request failed validation",
            extra={
                "path": request.url.path,
                "method": request.method,
                "fields": [f["field"] for f in fields],
            },
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            # The pydantic list stays in ``detail`` so existing clients —
            # including this product's own frontend — keep reading it the way
            # they always have. It goes through jsonable_encoder because a
            # validator that raised carries the exception object in ``ctx``,
            # which json.dumps cannot serialise.
            #
            # Bounded first: the list carries the rejected value in each
            # error's ``input``, so an unbounded one made every 422 in the API
            # a reflector of whatever the caller sent.
            content=error_body(
                422,
                jsonable_encoder(_bounded_errors(exc)),
                code="validation_error",
                fields=fields,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 5xx raised deliberately is still worth a stack-free error line.
        log = logger.warning if exc.status_code >= 500 else logger.info
        log(
            "Request rejected",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": exc.status_code,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.status_code, _bounded_detail(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        # A unique or FK violation is the database enforcing a rule the request
        # broke — a 409, not a 500. The driver's message names table and index
        # and is not repeated to the caller.
        logger.warning(
            "Database constraint violated",
            extra={"path": request.url.path, "method": request.method},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_body(
                409,
                "That record conflicts with one that already exists.",
                code="conflict",
            ),
        )

    @app.exception_handler(OperationalError)
    async def _operational(request: Request, exc: OperationalError) -> JSONResponse:
        # A dropped connection or an exhausted pool: the request is retryable
        # and the caller should be told so, rather than shown a 500.
        logger.error(
            "Database unavailable",
            extra={"path": request.url.path, "method": request.method},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_body(
                503, "The database is temporarily unavailable. Please retry.",
                code="service_unavailable",
            ),
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception(
            "Unhandled database error",
            extra={"path": request.url.path, "method": request.method},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(500, _opaque_message(), code="internal_error"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception",
            extra={
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
            },
        )
        from app.core.middleware import SecurityHeadersMiddleware

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body(500, _opaque_message(), code="internal_error"),
            # Set here rather than left to the user middleware. A handler for a
            # *specific* exception type is installed in Starlette's inner
            # ExceptionMiddleware, so its response travels back out through the
            # user middleware and picks headers up on the way. This one is the
            # bare ``Exception`` handler, which lives in the outermost
            # ServerErrorMiddleware — nothing runs after it. Without these, the
            # one response type that most needs hardening is the only one
            # served without security headers or a traceable id.
            headers={
                "X-Request-ID": get_correlation_id() or "-",
                "X-Correlation-ID": get_correlation_id() or "-",
                **SecurityHeadersMiddleware._BASE,
                "Content-Security-Policy": (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                ),
            },
        )


def _opaque_message() -> str:
    """What a 500 says. Never the exception — only how to ask about it."""
    correlation = get_correlation_id() or "-"
    if settings.debug:
        return f"Internal server error. Check the logs for correlation id {correlation}."
    return (
        "Something went wrong on our side. The problem has been logged; "
        f"quote reference {correlation} if you contact support."
    )


__all__ = ["HTTPException", "error_body", "error_code", "register_exception_handlers"]
