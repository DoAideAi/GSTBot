"""DoAide GST FastAPI application entrypoint."""
from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import settings, validate_startup_config
from app.core.database import check_database, engine
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    AccessLogMiddleware,
    CorrelationIdMiddleware,
    GptActionsCorsMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.openapi import install_openapi
from app.core.redis_client import close as redis_close
from app.core.redis_client import ping as redis_ping
from app.core.storage import check_upload_dir
from app.routers import (
    advisor,
    alerts,
    auth,
    businesses,
    dashboard,
    feedback,
    filing,
    gpt,
    invoices,
    itc,
    misc,
    oauth,
    reconciliation,
    referrals,
    seo,
    subscriptions,
    suppliers,
    whatsapp,
)

logger = logging.getLogger(__name__)

DESCRIPTION = """
GST compliance for Indian SMBs: read invoices, reconcile them against the
portal's GSTR-2B, work out what input tax credit is actually safe to claim, and
prepare the return.

### Authentication

Every endpoint except `/health*` and `/meta/*` needs a bearer token. Get one
from `POST /auth/register` (which creates the business too) or
`POST /auth/login`, then send it as `Authorization: Bearer <token>`.

### Tenancy

A token identifies a *business* — one GST registration — and every query is
filtered by it. A row belonging to another tenant answers **404**, not 403: a
403 would confirm that the id exists, which is enough to probe a competitor's
invoice volume.

### Errors

Every error has the same shape, whatever raised it:

```json
{
  "detail": "Invoice not found",
  "error": {"code": "not_found", "status": 404, "message": "Invoice not found"},
  "correlation_id": "9f2c1a0b4e7d5a63"
}
```

Branch on `error.code` rather than on the prose in `detail`. The
`correlation_id` also comes back as the `X-Request-ID` header on every
response, and is what support needs to find the request in the logs.

### Rate limits

Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`. A 429 carries
`Retry-After` in seconds. Limits are keyed per authenticated user, falling back
to the client address for anonymous callers — so an office behind one NAT does
not share a single budget.

`POST /auth/login` carries a second budget on top, keyed by the account being
attempted rather than by the caller, so that failed sign-ins against one
account are capped no matter how many addresses they arrive from. It counts
only failures and is handed straight back on a correct password, so a client
that signs in successfully never meets it.

### Money

Every monetary value is a decimal *string*, not a float — `"1234.56"`. GST is
computed to the paisa and a float cannot hold 18% of ₹1,234.56 exactly. Parse
these with a decimal type.
"""

TAGS_METADATA = [
    {
        "name": "health",
        "description": (
            "Liveness, readiness and the public metadata the sign-up form needs. "
            "No authentication."
        ),
    },
    {
        "name": "auth",
        "description": (
            "Registration, login and the current session. Registering creates the "
            "business and its owner in one step and returns a usable token, so "
            "there is no second login round trip."
        ),
    },
    {
        "name": "invoices",
        "description": (
            "Upload, list, correct and re-extract invoices. An upload is stored and "
            "committed before it is parsed, so a rate-limited model costs a retry "
            "rather than the document."
        ),
    },
    {
        "name": "dashboard",
        "description": "Everything the landing screen shows, in one round trip.",
    },
    {
        "name": "reconciliation",
        "description": (
            "Import a GSTR-2B and match it against the purchase register. Runs "
            "accumulate rather than overwrite: a period is reconciled repeatedly as "
            "suppliers file late, and 'what did we know, and when' is the question "
            "an ITC reversal turns on months later."
        ),
    },
    {
        "name": "itc",
        "description": (
            "The input tax credit position: what is available, what reverses under "
            "Rules 37/42/43, and how a credit settles against a liability in the "
            "statutory order."
        ),
    },
    {
        "name": "filing",
        "description": (
            "Validate a period, generate GSTR-1 or GSTR-3B in the portal's JSON "
            "shape, and export either as JSON for the offline utility or CSV for a "
            "human."
        ),
    },
    {
        "name": "suppliers",
        "description": (
            "Counterparties and their compliance scores, built from this tenant's "
            "own matched invoices rather than from a shared reputation."
        ),
    },
    {
        "name": "alerts",
        "description": (
            "What the business still has to act on, and the two things it can do "
            "about one: mark it seen, or dismiss it. Nothing here is delivered "
            "anywhere yet — an alert lives in the product, so `channel` and "
            "`sent_at` are null on every row."
        ),
    },
    {
        "name": "gpt",
        "description": (
            "The free GST tools as ChatGPT GPT Actions: GSTIN validation, HSN "
            "search, GST calculation, invoice data and filing dates. Public, "
            "stateless, rate-limited by address."
        ),
    },
    {
        "name": "subscriptions",
        "description": (
            "Subscription tiers, Razorpay payment flow, and API usage tracking. "
            "The pricing endpoint is public; everything else needs a bearer token."
        ),
    },
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Boot checks. Anything fatal has already raised out of Settings by now.

    What is left is the reporting tier: log the resolved configuration (with
    secrets redacted), warn about anything questionable, and probe the two
    dependencies once — so a misconfigured deployment says so in its first ten
    log lines rather than on its first upload.
    """
    configure_logging(settings.log_level, settings.log_format)
    logger.info("Starting %s", settings.app_name, extra=settings.startup_report())

    for warning in validate_startup_config(settings):
        logger.warning("Configuration warning: %s", warning)

    # Created at startup rather than on first upload, so a bad path or a
    # read-only volume fails at deploy time instead of on a user's file. The
    # same probe backs ``/health`` from then on: this line is the only place a
    # volume that went bad *after* boot used to be noticed, and it was never
    # written again.
    storage_ok, storage_error = check_upload_dir()
    if storage_error == "ReadOnly":
        logger.error("UPLOAD_DIR %s is not writable — uploads will fail", settings.upload_dir)
    elif not storage_ok:
        logger.error("UPLOAD_DIR %s could not be created: %s", settings.upload_dir, storage_error)

    database_ok, database_error = check_database()
    if database_ok:
        logger.info("Database reachable")
    else:
        # Not fatal: a database still coming up is normal in a compose or
        # Kubernetes start, and the readiness probe is what holds traffic back
        # until it answers.
        logger.error("Database unreachable at startup: %s", database_error)

    if redis_ping():
        logger.info("Redis reachable")
    else:
        logger.warning(
            "Redis unreachable — rate limiting falls back to per-process counters"
            + (", and queued parsing is unavailable" if settings.celery_enabled else "")
        )

    yield

    # Shutdown. systemd sends SIGTERM and waits TimeoutStopSec before SIGKILL;
    # uvicorn drains in-flight requests first, so by here the pools are idle and
    # releasing them is the difference between a socket closed now and one the
    # server reaps on its own schedule. On a rolling restart that overlap is
    # counted against Postgres's max_connections and Redis's maxclients by both
    # the old process and the new one at once.
    #
    # Neither of these may raise: an exception escaping lifespan shutdown turns
    # a clean stop into a non-zero exit, which systemd records as a failed unit
    # and which makes an ordinary deploy look like a crash.
    logger.info("Shutting down %s", settings.app_name)

    await advisor.close_clients()

    try:
        redis_close()
    except Exception as exc:  # noqa: BLE001 - shutdown is not a place to fail
        logger.warning("Redis client did not close cleanly: %s", exc)

    try:
        engine.dispose()
    except Exception as exc:  # noqa: BLE001 - shutdown is not a place to fail
        logger.warning("Database pool did not dispose cleanly: %s", exc)

    logger.info("Shutdown complete")


def derive_session_key(jwt_secret: str) -> str:
    """Derive a separate signing key for SessionMiddleware from the JWT secret."""
    return hmac.new(
        jwt_secret.encode(), b"starlette-session-signing", hashlib.sha256
    ).hexdigest()


def create_app() -> FastAPI:
    configure_logging(settings.log_level, settings.log_format)

    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="AI GST compliance for Indian SMBs.",
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        contact={"name": "DoAide GST", "url": "https://gst.doaide.com"},
        license_info={"name": "Proprietary"},
        # Only the code every route can really answer. 401 and 429 were here
        # too, which published them for the public allowlist and for the one
        # probe exempt from the limiter; they are derived per route by
        # ``install_openapi`` below. See app/core/openapi.py.
        responses={
            500: {"description": "Unexpected error. Quote `correlation_id` to support."},
        },
    )

    register_exception_handlers(application)

    # Middleware runs in the reverse of the order it is added, so this block
    # reads bottom-up: CORS runs first, then CorrelationId (everything below it
    # logs with an id bound), then the security headers, then the body size
    # ceiling, then the global rate limit, then the access log, then
    # compression, with the route last.
    #
    # A GSTR-2B report or a period's invoice list is repetitive JSON that
    # compresses roughly 10:1; below 1 KB the header costs more than it saves.
    application.add_middleware(GZipMiddleware, minimum_size=1024)
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(RateLimitMiddleware)
    # Above the rate limiter, so a body too large to accept is refused without
    # spending the caller's budget on it, and below the correlation id, so the
    # 413 carries one like every other response.
    application.add_middleware(RequestSizeLimitMiddleware)
    application.add_middleware(
        SecurityHeadersMiddleware,
        docs_paths=tuple(p for p in (docs_url, redoc_url, openapi_url) if p),
    )
    application.add_middleware(CorrelationIdMiddleware)
    # Outermost, so that it decorates *every* response and not only the ones a
    # route produced. It used to sit closest to the route, which meant any
    # middleware that answered on its own — the rate limiter's 429, the size
    # ceiling's 413 — returned without ``Access-Control-Allow-Origin``, and a
    # browser refused to hand that response to the caller at all.
    #
    # The 429 is the one that mattered. ``expose_headers`` below names
    # ``Retry-After`` and the ``X-RateLimit-*`` pair precisely so a browser
    # client can back off, and those headers are set on exactly the response
    # the browser was throwing away: the SPA saw an indistinguishable network
    # error instead of "you are over your limit, wait 29 seconds". A 401 or a
    # 500 was never affected, because those come from below this line, which is
    # what kept the gap narrow enough to go unnoticed.
    #
    # Being outermost also means a CORS preflight is answered here and never
    # reaches the limiter, which is what ``RateLimitMiddleware`` was skipping
    # OPTIONS by hand to achieve. That check stays: an OPTIONS without an
    # ``Origin`` is not a preflight and still arrives.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        # Named rather than "*": with credentials allowed a wildcard is
        # rejected by browsers anyway, and the list documents what a client is
        # expected to send.
        allow_headers=[
            "Authorization", "Content-Type",
            "X-Request-ID", "X-Correlation-ID", "X-Business-Id",
        ],
        # Without this a browser client cannot read the id it needs to report a
        # problem, nor the rate-limit budget it should back off against, nor
        # the filename on an export.
        expose_headers=[
            "X-Request-ID",
            "X-Correlation-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
            "Content-Disposition",
        ],
        max_age=600,
    )

    application.add_middleware(
        SessionMiddleware,
        secret_key=derive_session_key(settings.jwt_secret),
        https_only=settings.is_production,
        same_site="lax",
        max_age=14400,
    )

    # Outermost of all, so a preflight from ChatGPT is answered before the
    # credentialed app-wide policy above can refuse an origin it does not list.
    application.add_middleware(GptActionsCorsMiddleware, prefix=f"{settings.api_v1_prefix}/gpt/")

    prefix = settings.api_v1_prefix
    application.include_router(advisor.router, prefix=prefix)
    application.include_router(misc.router, prefix=prefix)
    application.include_router(feedback.router, prefix=prefix)
    application.include_router(auth.router, prefix=prefix)
    application.include_router(oauth.router, prefix=prefix)
    application.include_router(businesses.router, prefix=prefix)
    application.include_router(invoices.router, prefix=prefix)
    application.include_router(dashboard.router, prefix=prefix)
    application.include_router(reconciliation.router, prefix=prefix)
    application.include_router(itc.router, prefix=prefix)
    application.include_router(filing.router, prefix=prefix)
    application.include_router(suppliers.router, prefix=prefix)
    application.include_router(alerts.router, prefix=prefix)
    application.include_router(subscriptions.router, prefix=prefix)
    application.include_router(referrals.router, prefix=prefix)
    application.include_router(seo.router, prefix=prefix)
    application.include_router(whatsapp.router, prefix=prefix)
    application.include_router(gpt.router, prefix=prefix)

    @application.get("/", include_in_schema=False)
    def root() -> dict[str, str | None]:
        return {
            "app": settings.app_name,
            "version": settings.app_version,
            "docs": docs_url,
            "health": f"{prefix}/health",
        }

    # After the routers, though the walk itself is lazy: the spec is derived
    # from the assembled table, so it has to be able to see all of it.
    install_openapi(application)

    return application


app = create_app()
