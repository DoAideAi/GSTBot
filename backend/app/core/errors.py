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

Error code catalog
------------------
Branch on ``error.code``, not on ``detail`` (which is prose and may change).

``bad_request`` (400)
    The request is structurally wrong — a body where the route expects none, or
    a content type the route does not accept. Fix the request, do not retry.

``unauthorized`` (401)
    No valid bearer token. The token is missing, expired or malformed. Re-
    authenticate and retry with a fresh ``Authorization: Bearer <token>`` header.

``payment_required`` (402)
    The business's subscription does not cover this action — typically an
    invoice upload above the plan's monthly limit. Upgrade the plan or wait for
    the next billing period.

``forbidden`` (403)
    The caller is authenticated but lacks the required role. ``detail`` names
    the role held and who to ask for elevation. A viewer hitting a write route
    always sees this; owners and accountants never do.

``paid_plan_required`` (403)
    The feature needs an active paid subscription and this business has none,
    or its paid period has run out. Distinct from ``forbidden``, which is about
    the caller's role: here the caller's role is fine and the *plan* is not, so
    the action is to upgrade (see ``/pricing``), not to ask an owner.

``not_found`` (404)
    The resource does not exist **or belongs to another tenant**. Cross-tenant
    reads deliberately answer 404, not 403, to avoid confirming that the id
    exists. Check the id and the ``X-Business-Id`` header.

``method_not_allowed`` (405)
    The HTTP method is wrong for this path — e.g. POST to a GET-only route.

``conflict`` (409)
    A database uniqueness constraint was violated — typically a duplicate GSTIN,
    email, or invoice number within the same business. The response does not
    name the constraint (that would leak schema); ``detail`` says what collided.

``payload_too_large`` (413)
    The upload exceeds ``MAX_UPLOAD_MB`` (default 15 MB). Compress or split
    the file before retrying.

``unsupported_media_type`` (415)
    The uploaded file's MIME type is not one the endpoint accepts. Check the
    route's documentation for the accepted types.

``validation_error`` (422)
    One or more fields failed Pydantic validation. ``error.fields`` is a list
    of ``{field, message, type}`` entries pinpointing each failure. The rejected
    value is echoed (truncated at 200 characters) unless the field looks like a
    secret (password, token, api_key), which is redacted.

``rate_limited`` (429)
    Too many requests. The ``Retry-After`` header says how many seconds to wait.
    Per-route buckets are documented in each route's OpenAPI spec; a global
    per-address counter of 300/minute underlies all of them.

``internal_error`` (500)
    An unhandled exception. The real error is in the server log, keyed by the
    ``correlation_id`` in the response. Retrying may help if it was transient.

``upstream_error`` (502)
    A dependency (OpenRouter, Razorpay, SMTP) returned an unexpected response.
    The request may succeed on retry.

``service_unavailable`` (503)
    The database or a required service is temporarily unreachable. The
    ``Retry-After`` header is set. Safe to retry after the indicated delay.

``upstream_timeout`` (504)
    A dependency did not respond in time. Retry after a short delay.
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
from app.core.headers import security_headers
from app.core.logging import get_correlation_id
from app.core.sanitize import encodable

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


# What a stored failure reason says in place of an exception's own text when
# that text is about the machine rather than the document.
DATABASE_FAILURE_REASON = (
    "The result could not be saved because of a problem on our side. Try again; "
    "if it keeps failing, contact support."
)
STORAGE_FAILURE_REASON = (
    "The stored file could not be read because of a problem on our side. Try "
    "again; if it keeps failing, upload the document again."
)
# Absolute POSIX paths of two or more segments: an upload directory, a
# library's install path, a temp file. Two segments so a fraction like "1/2"
# or a date like "15/04/2026" in a document's own message is left alone.
_ABSOLUTE_PATH = re.compile(r"(?<![\w.])/(?:[\w.@+-]+/)+[\w.@+-]*")


def public_reason(exc: BaseException, *, limit: int = 2000) -> str:
    """An exception's message, fit to store on a row the API returns.

    A failed parse and a failed reconciliation both record why on the row —
    ``parse_error``, ``error`` — and both rows go straight back to the caller.
    Storing ``str(exc)`` handed the caller whatever the exception carried: a
    SQLAlchemy error's ``[SQL: ...]`` and ``[parameters: ...]`` (the statement,
    the table, and the tenant's own figures), an ``OSError``'s absolute path
    under the upload directory, a library's install path. None of it is
    something the reader can act on, and all of it maps the server for
    someone who can.

    The full exception is still logged with its traceback at every call site,
    which is where an operator debugging a bad volume mount goes for the path.
    What remains here is what the user can do about it: a database or storage
    failure becomes a sentence saying so, and any other message keeps its words
    with absolute paths taken out — a parser's own reason is usually the most
    useful thing on the screen.
    """
    if isinstance(exc, SQLAlchemyError):
        return DATABASE_FAILURE_REASON
    if isinstance(exc, OSError) and not isinstance(exc, ConnectionError | TimeoutError):
        return STORAGE_FAILURE_REASON
    message = _ABSOLUTE_PATH.sub("<path>", str(exc)).strip()
    return (message or type(exc).__name__)[:limit]


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
    # An error body quotes what the caller sent, and JSONResponse encodes to
    # UTF-8: one escaped half-pair in a refused field was a 500 on every route.
    return encodable(body)


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


# How far into a rejected body the echo goes.
#
# ``_bounded`` used to look at the top level only. That left two holes, both
# reachable with nothing but a JSON body: a dict of a few keys whose *values*
# were megabytes each came back whole — the reflector the ceiling above exists
# to close, one level down — and a body nested a thousand objects deep made
# ``jsonable_encoder`` recurse past the interpreter's limit inside this
# handler, so a request that failed validation answered 500 instead of 422.
# Every real field in this API sits within a few levels of the top; past this
# depth a value is summarised, not walked.
_MAX_ECHOED_DEPTH = 4


def _bounded(value: Any, depth: int = 0) -> Any:
    """*value* with anything longer than the ceiling above cut down.

    Strings are shortened in place. A container is walked, to
    :data:`_MAX_ECHOED_DEPTH`, with each member bounded the same way; one with
    more members than the ceiling, or nested below the depth limit, has no
    meaningful prefix, so it is replaced by a note of its type rather than a
    mangled fragment of itself.
    """
    if isinstance(value, str):
        if len(value) <= _MAX_ECHOED_INPUT:
            return value
        return value[:_MAX_ECHOED_INPUT] + _TRUNCATION_MARKER
    if isinstance(value, (dict, list, tuple, set)):
        if len(value) > _MAX_ECHOED_INPUT or (value and depth >= _MAX_ECHOED_DEPTH):
            return f"<{type(value).__name__} of {len(value)} items{_TRUNCATION_MARKER}>"
        if isinstance(value, dict):
            return {
                _bounded(key, depth + 1): _bounded(item, depth + 1)
                for key, item in value.items()
            }
        return [_bounded(item, depth + 1) for item in value]
    return value


class CodedHTTPException(HTTPException):
    """An ``HTTPException`` whose ``error.code`` is not the status's default.

    For the one case where two refusals share a status and a client must be
    able to tell them apart without reading the prose — see the catalog above.
    """

    def __init__(self, status_code: int, detail: Any, *, code: str) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


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


# What pydantic puts in front of every message a custom validator raises. The
# sentence after it is ours, written for the person filling the form; the
# prefix is pydantic's name for the mechanism, and it reached them verbatim —
# "Password: Value error, A password cannot be only spaces."
_VALIDATOR_PREFIX = re.compile(r"^(?:Value error|Assertion failed), ")


def _bounded_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """``exc.errors()`` with every echoed value bounded.

    Applied to the whole error dict rather than to ``input`` alone: ``msg``
    quotes the value too on some pydantic errors, and ``ctx`` carries whatever
    a custom validator put in its message.
    """
    bounded: list[dict[str, Any]] = []
    for error in exc.errors():
        entry = {key: _bounded(value) for key, value in error.items()}
        if isinstance(entry.get("msg"), str):
            entry["msg"] = _VALIDATOR_PREFIX.sub("", entry["msg"], count=1)
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
            content=error_body(
                exc.status_code, _bounded_detail(exc.detail), code=getattr(exc, "code", None)
            ),
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
                **security_headers(),
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


__all__ = [
    "CodedHTTPException",
    "HTTPException",
    "error_body",
    "error_code",
    "register_exception_handlers",
]
