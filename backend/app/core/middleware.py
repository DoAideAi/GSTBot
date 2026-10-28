"""Request-scoped middleware: identity, logging, limits and response headers.

Ordering matters and is set in ``create_app``. Starlette runs middleware in the
reverse of the order they are added, so the correlation-id middleware is added
*last* and therefore runs *first* — everything after it, including the rate
limiter's rejection and the exception handlers' 500, is logged and answered
with an id already bound.
"""
from __future__ import annotations

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.errors import error_body
from app.core.headers import security_headers
from app.core.logging import (
    bind_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)
from app.core.rate_limit import check_global, client_ip

logger = logging.getLogger("app.access")

# Header a client (or an upstream proxy) may use to supply its own id, in the
# order they are honoured.
_INBOUND_HEADERS = ("x-request-id", "x-correlation-id")

# Paths whose access lines are noise: a load balancer hits health every few
# seconds and would otherwise be the bulk of the log volume.
#
# ``/health`` unprefixed is deliberate — ``API_V1_PREFIX`` is configurable and
# a deployment that shortens it still wants its probe quiet. ``/metrics`` was
# here too, and nothing in this product has ever served it.
_QUIET_PATHS = frozenset({"/health", "/api/v1/health", "/api/v1/health/live"})

# Paths the *global rate limit* skips. A strict subset of the quiet set, and
# the two are separate decisions that had been sharing one list.
#
# "Do not log this" is about volume and is safe to say about any probe. "Do not
# count this" is a hole, and only worth opening for a probe that costs nothing
# to serve: an orchestrator polls liveness every few seconds from one address,
# and rate-limiting it would eventually kill a pod for being healthy — but
# liveness touches no dependency, so an unlimited flood of it costs one dict.
#
# ``/api/v1/health`` is a different endpoint wearing a similar name. It runs a
# ``SELECT 1`` on a pooled connection and pings Redis on every call, and being
# in the exempt set made it the one unauthenticated route in the product that
# could be hammered without limit into the connection pool the API serves every
# tenant from. ``/health/ready`` does the same work and was never exempt, which
# is what gives away that the sharing was accidental rather than a decision.
#
# The global default is 300 a minute per address; a load balancer probing every
# five seconds spends twelve of them, so the probes keep working and the flood
# does not.
#
# ``/metrics`` was the other entry, and there is no such route — no exporter
# has ever been mounted, in this app or in front of it. An exemption naming a
# path nothing serves is not harmless: the limiter checks the path before the
# router does, so every request to it was answered 404 without being counted,
# which is an unmetered path in a set whose whole subject is which paths may go
# uncounted and why. Whichever way a metrics endpoint eventually arrives, the
# decision to exempt it should be made then, against what it costs to serve.
_UNLIMITED_PATHS = frozenset({"/api/v1/health/live"})


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind an id to the request context and echo it on the response.

    An id supplied by the caller is reused when it survives sanitising, so a
    trace that starts in the frontend or an upstream gateway stays one trace.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = ""
        for header in _INBOUND_HEADERS:
            supplied = sanitize_correlation_id(request.headers.get(header))
            if supplied:
                break

        correlation_id = bind_correlation_id(supplied)
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)

        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request, with its duration and outcome.

    Query strings are deliberately not logged: periods and GSTINs travel there,
    and a log aggregator is a lower-trust store than the database.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers turn this into a 500 response; the access
            # line still has to exist, and has to say the request failed.
            #
            # The same fields as a line that answered, and for a stronger
            # reason: a write that crashed half-way is the request an operator
            # most needs attributed, and the auth dependencies had already
            # stamped who it was before the handler raised. This branch used
            # to carry method, path and duration alone — so a 500 on
            # ``POST /filing/gstr3b/filed`` said nothing about who was
            # recording what, and not even from where.
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "%s %s failed", request.method, request.url.path,
                extra=_line_fields(request, 500, duration_ms),
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        # Rate-limit headers, if a limiter dependency ran on this route.
        decision = getattr(request.state, "rate_limit", None)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)

        if request.url.path in _QUIET_PATHS and response.status_code < 400:
            return response

        level = logging.INFO
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING

        logger.log(
            level,
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra=_line_fields(request, response.status_code, duration_ms),
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Response headers that cost nothing and close off whole bug classes.

    The set itself lives in ``app.core.headers``, which the unhandled-500
    handler shares. The docs pages are exempt from the CSP — Swagger UI loads
    its own bundle — and they are only mounted when enabled.
    """

    def __init__(self, app, docs_paths: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self._docs_paths = docs_paths

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in security_headers(
            csp=request.url.path not in self._docs_paths
        ).items():
            response.headers.setdefault(header, value)
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized body on its declared length, before anything reads it.

    The upload routes already check ``len(content)`` and answer 413, and that
    check happens one step too late to be the bound it looks like: by the time
    a route runs, Starlette has received the whole body and spooled it, and
    ``await file.read()`` then copies all of it into memory to be measured. The
    JSON routes had no check at all — a 20 MB body to ``/itc/set-off`` was
    decoded and validated in full.

    ``Content-Length`` is a claim the client makes and this trusts it in the
    only direction that is safe: a body *declaring* more than the ceiling is
    refused without being read, and one declaring less is still measured by the
    route that receives it. Under-declaring therefore buys nothing.

    A body with no declared length — chunked transfer encoding — is not bounded
    here, and is the reason the edge's ``request_body max_size`` stays where it
    is rather than being replaced by this. What this adds is the bound the
    *application* is entitled to have of its own: one that matches its own
    upload limit rather than sitting twice above it, and that holds for a
    caller reaching the API on the Docker bridge without passing the edge.
    """

    # A body is only ever sent with these; the rest are refused for having one
    # at all long before size could matter.
    _BODIED_METHODS = frozenset({"POST", "PUT", "PATCH"})

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in self._BODIED_METHODS:
            return await call_next(request)

        declared = request.headers.get("content-length", "")
        limit = settings.max_request_bytes
        # Anything unparseable is left to the server that framed the request:
        # guessing at a malformed length would refuse bodies over a number
        # nobody sent.
        if not declared.isdigit() or int(declared) <= limit:
            return await call_next(request)

        logger.warning(
            "Request body over the ceiling refused",
            extra={
                "http_path": request.url.path,
                "http_method": request.method,
                "status_code": 413,
                "client_ip": _client_ip(request),
            },
        )
        megabytes = limit // (1024 * 1024)
        return JSONResponse(
            status_code=413,
            content=error_body(
                413,
                f"Request body exceeds the {megabytes} MB limit.",
                code="payload_too_large",
            ),
            headers={"X-Request-ID": get_correlation_id() or "-"},
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """The blanket per-caller ceiling, applied before routing.

    Per-endpoint limits are dependencies (see ``app.core.rate_limit``); this is
    the one that also covers requests to paths that do not exist, which is what
    a scanner generates.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS" or request.url.path in _UNLIMITED_PATHS:
            # A CORS preflight is not a request the caller chose to make, and
            # rejecting one turns a rate limit into an opaque browser error.
            return await call_next(request)

        decision = check_global(request)
        if decision is not None and not decision.allowed:
            logger.warning(
                "Global rate limit exceeded",
                extra={
                    "http_path": request.url.path,
                    "client_ip": _client_ip(request),
                    "status_code": 429,
                },
            )
            response = JSONResponse(
                status_code=429,
                content=error_body(
                    429,
                    f"Too many requests. Try again in {decision.retry_after}s.",
                    code="rate_limited",
                ),
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            # The correlation middleware runs outside this one and will add the
            # id header on the way out, but the body is built here.
            response.headers["X-Request-ID"] = get_correlation_id() or "-"
            return response

        return await call_next(request)


# ``request.state`` attributes the auth dependencies set, and the access-line
# field each becomes. See ``get_current_user`` and ``get_active_tenant`` in
# ``app.core.deps`` for when each is stamped.
_ACTOR_STATE_FIELDS = ("user_id", "business_id", "role")


def _line_fields(request: Request, status_code: int, duration_ms: float) -> dict[str, object]:
    """Everything an access line carries, whether the request answered or raised.

    One builder for both outcomes so the two lines cannot drift apart again:
    the fields a support engineer greps for have to be the same fields on the
    line that says ``failed``.
    """
    fields: dict[str, object] = {
        "http_method": request.method,
        "http_path": request.url.path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "client_ip": _client_ip(request),
        "user_agent": request.headers.get("user-agent", "")[:200],
    }
    # Who acted, and for which business. This line is the only audit trail
    # the product keeps — no table records who filed a return or marked an
    # invoice paid — and a client's filing recorded by a linked accountant
    # through ``X-Business-Id`` is otherwise indistinguishable from the
    # owner recording it. Read off ``request.state`` because the identity
    # is resolved by the auth dependencies, not here: the middleware sees
    # a bearer token it has no business decoding twice, and reading the
    # verdict those dependencies reached keeps one place responsible for
    # what a token means. Absent on a public route or a refused token, and
    # left out rather than nulled so a line says exactly what was known.
    fields.update(_actor_fields(request))
    return fields


def _actor_fields(request: Request) -> dict[str, object]:
    """The identity fields the auth dependencies stamped on this request, if any."""
    return {
        name: getattr(request.state, name)
        for name in _ACTOR_STATE_FIELDS
        if hasattr(request.state, name)
    }


def _client_ip(request: Request) -> str:
    return client_ip(request)


# The origins ChatGPT's GPT builder and its clients run on. Actions themselves
# are fetched server-side by OpenAI and send no ``Origin``, so this is for the
# builder's "Test" panel and any browser client OpenAI ships later.
GPT_ACTIONS_ORIGINS = frozenset(
    {"https://chat.openai.com", "https://chatgpt.com", "https://platform.openai.com"}
)


class GptActionsCorsMiddleware:
    """CORS for OpenAI's origins on ``/gpt/*``, and nowhere else.

    A second policy rather than three more entries in ``BACKEND_CORS_ORIGINS``:
    that list is credentialed, so adding OpenAI to it would let a page on
    chatgpt.com make requests to *every* route carrying the user's cookies.
    These routes are public and stateless, so the grant here carries no
    credentials and stops at the prefix.

    Added outermost, so a preflight is answered before the app-wide
    ``CORSMiddleware`` — which does not know these origins — can refuse it. A
    preflight from any other origin falls through to that middleware and gets
    its usual answer.

    Pure ASGI rather than ``BaseHTTPMiddleware``, which runs everything inside
    it in a child task. Outermost, that would put the correlation id
    ``CorrelationIdMiddleware`` binds in a context the 500 handler cannot see,
    and every unhandled error would quote ``-`` instead of the caller's id.
    """

    _METHODS = "GET, POST, OPTIONS"
    _HEADERS = (
        "Content-Type, Authorization, X-Request-ID, "
        "OpenAI-Conversation-ID, OpenAI-Ephemeral-User-ID"
    )
    _EXPOSE = "X-Request-ID, X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After"

    def __init__(self, app, prefix: str = "/api/v1/gpt/") -> None:
        self.app = app
        self._prefix = prefix

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self._prefix):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin not in GPT_ACTIONS_ORIGINS:
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": self._METHODS,
                    "Access-Control-Allow-Headers": self._HEADERS,
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
            await response(scope, receive, send)
            return

        async def decorate(message) -> None:
            if message["type"] == "http.response.start":
                out = MutableHeaders(scope=message)
                out["Access-Control-Allow-Origin"] = origin
                out["Access-Control-Expose-Headers"] = self._EXPOSE
                # The app-wide middleware adds ``Allow-Credentials: true`` to
                # every response that carries an Origin, listed or not. Next
                # to the grant above that would be a credentialed grant to
                # OpenAI, and nothing under this prefix reads a cookie.
                del out["access-control-allow-credentials"]
                out.add_vary_header("Origin")
            await send(message)

        await self.app(scope, receive, decorate)
