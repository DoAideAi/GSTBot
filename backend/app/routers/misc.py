"""Health and metadata routes — no auth, no database writes.

Three health endpoints rather than one, because an orchestrator asks three
different questions and answering them all with the same check is how a
transient database blip turns into every pod being killed at once:

* ``/health/live`` — is the process alive? Never touches a dependency.
* ``/health/ready`` — should traffic be routed here? Fails on a dead database,
  because an instance that cannot read invoices should leave the rotation.
* ``/health`` — the operator's view: every dependency, with its latency, and a
  ``health`` field that distinguishes "degraded" from "down". "Every" includes
  the upload volume — a disk is a dependency that fails, and it used to be
  probed once at boot and never again.

``/health`` returns 200 while degraded, on purpose. The product still ingests
invoices without a model provider (heuristics take over) and without Redis
(parsing runs inline), so a monitor has to be able to tell "AI is down" from
"the API is down" — and a 503 for the former would page someone at 3am over a
free-tier rate limit.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.config import settings
from app.core.database import check_database, get_db, pool_status
from app.core.deps import get_current_business, require_admin, require_paid_tier
from app.core.rate_limit import RateLimit
from app.core.redis_client import get_redis, mark_unavailable
from app.core.redis_client import ping as redis_ping
from app.core.storage import check_upload_dir
from app.models.business import Business
from app.models.invoice import Invoice
from app.models.mixins import utcnow
from app.models.subscriber import Subscriber
from app.schemas.misc import (
    BulkGstinRequest,
    BulkGstinResponse,
    ReminderSubscribeRequest,
    SubscriberRequest,
)
from app.services import gstin as gstin_service
from app.services import job_health
from app.services import usage as usage_service
from app.services.openrouter_client import is_configured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# These are public, so they are limited by address rather than by identity —
# there is no identity to key on before a caller has signed in.
_gstin_limit = RateLimit("gstin_lookup", "30/minute", by="ip")

# Longest input the GSTIN lookup will look at. A GSTIN is 15 characters; this
# leaves room for the spaces and hyphens people paste out of PDFs, which
# ``gstin.normalize`` strips. See the route for why it is bounded at all.
_GSTIN_INPUT_MAX = 64
_meta_limit = RateLimit("meta", "60/minute", by="ip")

# The two operator views cost real work per call, unlike the probes below them:
# ``/health`` runs a database round-trip and a Redis ping, and ``/health/jobs``
# opens a fresh Redis connection for the queue depth and then blocks the worker
# thread for up to a second waiting on a Celery broadcast ping. Both are public
# and have to stay that way — an operator watching the queue has no token to
# send — but public plus unmetered plus a second of held thread per request is
# a way to exhaust the pool from off the internet, with no account to disable
# afterwards. Limited by address, generously: this is a ceiling on abuse, not a
# polling budget, and a monitor scraping every 15s sits two orders of magnitude
# under it.
#
# Deliberately NOT applied to ``/health/live`` or ``/health/ready``. Those are
# the orchestrator's, they touch nothing expensive, and a throttled readiness
# probe reads as an unready instance — which would take pods out of rotation to
# defend against load that costs nothing to serve.
_ops_limit = RateLimit("ops_health", "60/minute", by="ip")


def _timed(check) -> tuple[bool, float, str | None]:
    """Run *check*, returning ``(ok, milliseconds, error_type)``.

    Swallows everything: a health endpoint that can itself 500 tells a monitor
    nothing it can act on.
    """
    started = time.perf_counter()
    try:
        ok, error = check()
    except Exception as exc:  # noqa: BLE001 - a health check never raises
        return False, round((time.perf_counter() - started) * 1000, 2), type(exc).__name__
    return ok, round((time.perf_counter() - started) * 1000, 2), error


def _integrations() -> dict[str, dict[str, Any]]:
    """Which optional integrations this deployment has, and what each one drives."""
    from app.routers import advisor
    from app.services import razorpay_client

    email_ready = bool(settings.alerts_email_enabled and settings.smtp_host)
    return {
        "advisor": {
            "status": "configured" if advisor.is_configured() else "unconfigured",
            "required_for": ["GST advisor chat"],
        },
        "payments": {
            "status": "configured" if razorpay_client.is_configured() else "unconfigured",
            "webhooks": bool(settings.razorpay_webhook_secret),
            "required_for": ["paid plans", "report purchases"],
        },
        "email": {
            "status": (
                "configured"
                if email_ready
                else "misconfigured"
                if settings.alerts_email_enabled
                else "disabled"
            ),
            "required_for": ["deadline alert emails"],
        },
    }


@router.get(
    "/health",
    summary="Full health report",
    description=(
        "Every dependency with its latency. Returns 200 even when degraded — "
        "read the `health` field, which is `ok`, `degraded` (a soft dependency "
        "is down and the product still works) or `unhealthy` (the database is "
        "unreachable, and the response is a 503)."
    ),
    responses={
        200: {"description": "The API is up. `health` says how healthy."},
        503: {"description": "The database is unreachable; this instance cannot serve."},
    },
    dependencies=[Depends(_ops_limit)],
)
def health(response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Liveness plus every dependency that can fail independently."""
    database_ok, database_ms, database_error = _timed(lambda: check_database(db))
    redis_ok, redis_ms, _ = _timed(lambda: (redis_ping(), None))
    storage_ok, storage_ms, storage_error = _timed(check_upload_dir)
    ai_configured = is_configured()

    checks: dict[str, Any] = {
        "database": {
            "status": "ok" if database_ok else "unavailable",
            "latency_ms": database_ms,
            **({"error": database_error} if database_error else {}),
            "pool": pool_status(),
        },
        "redis": {
            "status": "ok" if redis_ok else "unavailable",
            "latency_ms": redis_ms,
            # Names what is actually lost when it is down, so the person
            # reading this at 3am does not have to guess.
            "required_for": ["distributed rate limiting", "celery broker"],
        },
        "ai": {
            "status": "configured" if ai_configured else "unconfigured",
            "provider": "openrouter",
            "model": settings.openrouter_model,
        },
        # A real write, not a permission check: a full disk and a read-only
        # remount both pass ``os.access`` and both fail every upload. Rated
        # ``degraded`` rather than ``unhealthy`` because the rest of the
        # product — the dashboard, reconciliation, filing prep, every read —
        # is served from the database and keeps working; a 503 here would
        # take the instance out of rotation for a volume that is usually
        # shared with the instance that replaces it.
        "storage": {
            "status": "ok" if storage_ok else "unavailable",
            "latency_ms": storage_ms,
            **({"error": storage_error} if storage_error else {}),
            "path": settings.upload_dir,
            "required_for": ["invoice uploads"],
        },
        # Optional features, reported so a missing key is visible here rather
        # than as a 503 to whoever next uses the feature. Booleans only — no
        # key, host or account ever appears. They do not move ``health``: each
        # one switched off is a supported configuration.
        "integrations": _integrations(),
    }

    if not database_ok:
        overall = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not redis_ok or not ai_configured or not storage_ok:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        # The flat keys are kept for the monitors already watching them;
        # `checks` is where the detail lives.
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": "ok" if database_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
        "ai": "configured" if ai_configured else "unconfigured",
        "storage": "ok" if storage_ok else "unavailable",
        "health": overall,
        "checks": checks,
    }


@router.get(
    "/health/live",
    summary="Liveness probe",
    description=(
        "Answers only 'is this process running'. Touches no dependency on "
        "purpose — a database outage must not make an orchestrator restart "
        "every instance, which turns a recoverable blip into a cold start."
    ),
)
def liveness() -> dict[str, str]:
    return {"status": "alive", "app": settings.app_name, "version": settings.app_version}


@router.get(
    "/health/metrics",
    summary="Request volume, error rate and latency per hour (admins only)",
    description=(
        "Counts for every answered request except health probes, across all "
        "API workers, for the last `hours` UTC hours (oldest first) and in "
        "total: requests by status class, requests slower than one second, "
        "requests over their route's performance budget (see "
        "`app/core/budgets.py`) with the routes that missed it most in "
        "`over_budget_routes`, the 5xx error rate and the average response "
        "time. Kept for 48 hours.\n\n"
        "Restricted to `ADMIN_EMAILS`: traffic volume is business information. "
        "A 503 means Redis, where the counters live, cannot be reached."
    ),
    responses={
        401: {"description": "Not signed in."},
        403: {"description": "Signed in, but not a site administrator."},
        503: {"description": "Redis is unavailable, so there are no counters to read."},
    },
    dependencies=[Depends(_ops_limit), Depends(require_admin)],
)
def request_metrics(hours: int = Query(default=24, ge=1, le=48)) -> dict[str, Any]:
    result = metrics.summary(hours)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Request metrics are unavailable right now. Try again in a minute.",
        )
    return result


@router.get(
    "/health/jobs",
    summary="Background job health: workers, queue depth, and scheduled-job heartbeats",
    description=(
        "Whether a Celery worker answers a ping, how many messages are "
        "waiting in the broker's queue, and how long ago each scheduled job "
        "last finished versus how often it is supposed to run.\n\n"
        "Returns 200 even when degraded — read the `health` field. A stale "
        "job or an empty worker pool means the deadline sweep and the stalled-"
        "parse reaper are not running, which is worth paging on; it is not "
        "the API itself being down, so it is not a 503.\n\n"
        "Public and read-only, like the rest of `/health/*`."
    ),
    dependencies=[Depends(_ops_limit)],
)
def job_status() -> dict[str, Any]:
    """Celery worker reachability, broker queue depth, and job heartbeats."""
    workers = job_health.worker_status()
    queue = job_health.queue_status()
    jobs = job_health.job_statuses()
    stale_jobs = [j.name for j in jobs if j.stale]

    degraded = (
        (settings.celery_enabled and not workers.reachable)
        or not queue.reachable
        or bool(stale_jobs)
    )

    return {
        "health": "degraded" if degraded else "ok",
        "celery_enabled": settings.celery_enabled,
        "workers": {
            "reachable": workers.reachable,
            "names": workers.workers,
            **({"error": workers.error} if workers.error else {}),
        },
        "queue": {
            "name": job_health.DEFAULT_QUEUE,
            "reachable": queue.reachable,
            "depth": queue.depth,
            **({"error": queue.error} if queue.error else {}),
        },
        "jobs": [
            {
                "name": j.name,
                "last_run": j.last_run.isoformat() if j.last_run else None,
                "stale": j.stale,
            }
            for j in jobs
        ],
    }


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description=(
        "Whether this instance should receive traffic. 503 when the database "
        "is unreachable; Redis being down is reported but does not fail the "
        "probe, because uploads still parse inline without it."
    ),
    responses={503: {"description": "Not ready — the database is unreachable."}},
)
def readiness(response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    database_ok, database_ms, database_error = _timed(lambda: check_database(db))
    redis_ok, _, _ = _timed(lambda: (redis_ping(), None))

    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if database_ok else "not_ready",
        "database": "ok" if database_ok else "unavailable",
        "database_latency_ms": database_ms,
        "redis": "ok" if redis_ok else "unavailable",
        **({"error": database_error} if database_error else {}),
    }


# HEAD on the probes as well: uptime monitors and load balancers commonly use
# it, and the GET-only routes answered 405 — which reads as "down" while the API
# is serving. Same handlers, so the status matches GET's; kept out of the schema,
# where a second operation per route is only noise.
_PROBES = (("/health", health), ("/health/live", liveness), ("/health/ready", readiness))
for _path, _probe in _PROBES:
    # With the GET route's own dependencies: registered bare, HEAD /health ran
    # the database, Redis and storage probes without the per-route limit GET
    # /health carries — the same handler, cheaper to hammer by method alone.
    _get = next(
        r for r in router.routes if getattr(r, "path", None) == _path and "GET" in r.methods
    )
    router.add_api_route(
        _path,
        _probe,
        methods=["HEAD"],
        include_in_schema=False,
        dependencies=list(_get.dependencies),
    )


@router.get(
    "/meta/states",
    summary="GST state codes",
    description=(
        "The two-digit state code to name mapping, for the onboarding and "
        "filing forms. The first two digits of every GSTIN are one of these."
    ),
    response_model=dict[str, str],
    dependencies=[Depends(_meta_limit)],
)
def states() -> dict[str, str]:
    return gstin_service.STATE_CODES


@router.get(
    "/meta/gstin/{gstin}",
    summary="Validate a GSTIN",
    description=(
        "Checks the format and the check digit, and decodes the state and PAN "
        "a valid GSTIN encodes.\n\n"
        "Always 200: an invalid GSTIN comes back as "
        '`{"valid": false, "error": ...}` rather than a 4xx, because the '
        "sign-up form calls this on every keystroke and a 4xx per character is "
        "indistinguishable from the endpoint being broken. Input longer than "
        f"{_GSTIN_INPUT_MAX} characters is the exception and is refused.\n\n"
        "Public — it is called before an account exists."
    ),
    dependencies=[Depends(_gstin_limit)],
)
def validate_gstin(
    # The one route that echoes its own path segment back to an unauthenticated
    # caller: an unparseable input is answered with ``normalize(gstin)`` so the
    # form can show what it read. Unbounded, that made a 20KB path segment a
    # 20KB response body — work and bandwidth, before any account exists,
    # behind nothing but an IP-keyed limit.
    #
    # The ceiling is well clear of anything a person can type. A GSTIN is 15
    # characters, and this accepts the separators people paste out of PDFs and
    # spreadsheets ("27 AAPFU0939F 1ZV") with room to spare, so the documented
    # always-200 contract still holds for every keystroke the sign-up form
    # makes. What is refused is not a mistyped GSTIN; it is not a GSTIN.
    gstin: str = Path(max_length=_GSTIN_INPUT_MAX),
) -> dict[str, Any]:
    try:
        parts = gstin_service.parse(gstin)
    except gstin_service.InvalidGSTIN as exc:
        return {"gstin": gstin_service.normalize(gstin), "valid": False, "error": str(exc)}
    result = {
        "gstin": parts.gstin,
        "valid": True,
        "state_code": parts.state_code,
        "state_name": parts.state_name,
        "pan": parts.pan,
    }
    _record_lookup(result)
    return result


_bulk_gstin_limit = RateLimit("bulk_gstin", "30/minute")


@router.post(
    "/meta/gstin/bulk",
    response_model=BulkGstinResponse,
    summary="Validate up to 100 GSTINs at once",
    description=(
        "Accepts a list of GSTINs and returns validation results for each. "
        "Requires a paid subscription (SMB or CA plan)."
    ),
    responses={
        403: {"description": "No active paid subscription."},
    },
    dependencies=[Depends(_bulk_gstin_limit), Depends(require_paid_tier)],
)
def validate_gstins_bulk(
    body: BulkGstinRequest,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> BulkGstinResponse:
    results = []
    valid_count = 0
    for raw in body.gstins:
        try:
            parts = gstin_service.parse(raw)
            results.append({
                "gstin": parts.gstin,
                "valid": True,
                "state_code": parts.state_code,
                "state_name": parts.state_name,
                "pan": parts.pan,
            })
            valid_count += 1
        except gstin_service.InvalidGSTIN as exc:
            results.append({
                "gstin": gstin_service.normalize(raw),
                "valid": False,
                "error": str(exc),
            })
    # Counted on the Usage page as one bulk operation. Bookkeeping: a failure
    # to record it must not take back an answer that has already been worked out.
    try:
        usage_service.record_usage(db, business.id, "bulk_operation")
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Bulk GSTIN usage not recorded", extra={"business_id": business.id})
    return BulkGstinResponse(
        results=results,
        total=len(results),
        valid_count=valid_count,
        invalid_count=len(results) - valid_count,
    )


_RECENT_LOOKUPS_KEY = "gstbot:recent_lookups"
_RECENT_LOOKUPS_MAX = 20
_LOOKUP_COUNT_KEY = "gstbot:lookup_count"


def _masked_gstin(gstin: str) -> str:
    """The GSTIN with its PAN — characters 3 to 12 — hidden.

    The recent-lookups feed is public, and a full GSTIN in it said which
    business someone had just checked: a tenant vetting a supplier, or a
    competitor, published to every visitor. For a proprietorship the PAN inside
    it is the owner's personal one. The state code and the last three characters
    are enough for the feed to read as real activity and identify nobody.
    """
    if len(gstin) != 15:
        return "•" * len(gstin)
    return f"{gstin[:2]}{'•' * 10}{gstin[12:]}"


def _record_lookup(result: dict[str, Any]) -> None:
    """Best-effort: push a valid lookup into the recent list in Redis."""
    if not result.get("valid"):
        return
    client = get_redis()
    if client is None:
        return
    import json

    entry = json.dumps({
        "gstin": _masked_gstin(result["gstin"]),
        "state_name": result.get("state_name", ""),
        "valid": True,
    })
    try:
        pipe = client.pipeline(transaction=False)
        pipe.lrem(_RECENT_LOOKUPS_KEY, 1, entry)
        pipe.lpush(_RECENT_LOOKUPS_KEY, entry)
        pipe.ltrim(_RECENT_LOOKUPS_KEY, 0, _RECENT_LOOKUPS_MAX - 1)
        # The all-time counter behind /meta/stats. A re-lookup of the same
        # GSTIN counts again on purpose: the figure is "lookups served", the
        # work this API did, not "distinct GSTINs seen".
        pipe.incr(_LOOKUP_COUNT_KEY)
        pipe.execute()
    except Exception:  # noqa: BLE001
        mark_unavailable("recent lookup record failed")


@router.get(
    "/meta/recent-lookups",
    summary="Recently verified GSTINs",
    description=(
        "The last 20 valid GSTIN lookups, anonymised: no IP, no timestamp, and "
        "the PAN inside each GSTIN masked, so the state code and check digits "
        "are all that is shown. "
        "Public — shown on the lookup page for social proof."
    ),
    dependencies=[Depends(_meta_limit)],
)
def recent_lookups() -> dict[str, Any]:
    client = get_redis()
    if client is None:
        return {"lookups": []}
    import json

    try:
        raw = client.lrange(_RECENT_LOOKUPS_KEY, 0, _RECENT_LOOKUPS_MAX - 1)
        lookups = [json.loads(item) for item in raw]
        # Masked again on the way out: entries written before masking on the
        # way in still carry the full GSTIN until the list rotates them out.
        for lookup in lookups:
            lookup["gstin"] = _masked_gstin(str(lookup.get("gstin", "")))
        return {"lookups": lookups}
    except Exception:  # noqa: BLE001
        mark_unavailable("recent lookups read failed")
        return {"lookups": []}


# The landing page shows these numbers to anonymous visitors, so they must be
# real — the trust bar they feed refuses to invent a figure. Counting rows on
# every call would hand an unauthenticated route two COUNT(*) scans per hit,
# which is more pool time than /health's SELECT 1; a short in-process cache
# keeps the cost at one scan a minute per worker while staying fresh enough
# for numbers that only ever grow.
_STATS_TTL_SECONDS = 60.0
_stats_cache: tuple[float, dict[str, int]] | None = None


@router.get(
    "/meta/stats",
    summary="Aggregate usage statistics",
    description=(
        "Anonymous aggregate counts for social proof on the public pages: "
        "live businesses, invoices processed, and GSTIN lookups served.\n\n"
        "Public — rendered before any account exists, and none of it is any "
        "tenant's data. The lookup counter lives in Redis and reports 0 while "
        "Redis is unreachable; callers hide a figure rather than show a "
        "wrong one."
    ),
    response_model=dict[str, int],
    dependencies=[Depends(_meta_limit)],
)
def usage_stats(db: Session = Depends(get_db)) -> dict[str, int]:
    global _stats_cache
    now = time.monotonic()
    if _stats_cache is not None and now - _stats_cache[0] < _STATS_TTL_SECONDS:
        return _stats_cache[1]

    businesses = (
        db.query(sa_func.count(Business.id))
        .filter(Business.deleted_at.is_(None))
        .scalar()
        or 0
    )
    invoices = (
        db.query(sa_func.count(Invoice.id))
        .filter(Invoice.deleted_at.is_(None))
        .scalar()
        or 0
    )

    lookups = 0
    client = get_redis()
    if client is not None:
        try:
            lookups = int(client.get(_LOOKUP_COUNT_KEY) or 0)
        except Exception:  # noqa: BLE001
            mark_unavailable("lookup count read failed")

    stats = {"businesses": businesses, "invoices": invoices, "gstin_lookups": lookups}
    _stats_cache = (now, stats)
    return stats


_reminder_limit = RateLimit("reminder_subscribe", "10/minute", by="ip")


@router.post(
    "/meta/reminder-subscribe",
    summary="Subscribe to GST filing deadline reminders (legacy)",
    description=(
        "Captures an email address for GST filing deadline reminders. "
        "Public — called from the landing page before sign-in. "
        "Delegates to the subscribers endpoint."
    ),
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_reminder_limit)],
)
def reminder_subscribe(
    body: ReminderSubscribeRequest,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _upsert_subscriber(db, body.email, "landing")
    return {"subscribed": True}


# --------------------------------------------------------------------------
# Subscribers — email capture for filing-deadline reminders
# --------------------------------------------------------------------------

_subscriber_limit = RateLimit("subscriber", "10/minute", by="ip")


def _subscriber_hmac_secret() -> str:
    return settings.subscriber_hmac_secret or settings.jwt_secret


def make_unsubscribe_token(email: str) -> str:
    return hmac.new(
        _subscriber_hmac_secret().encode(),
        email.lower().encode(),
        hashlib.sha256,
    ).hexdigest()


def _upsert_subscriber(db: Session, email: str, source: str) -> bool:
    """Insert or resubscribe. Returns whether the email is newly subscribed."""
    normalised = email.lower().strip()
    existing = db.query(Subscriber).filter_by(email=normalised).first()
    if existing is not None:
        if existing.unsubscribed_at is not None:
            existing.unsubscribed_at = None
            existing.subscribed_at = utcnow()
            existing.source = source
            db.commit()
            return True
        return False
    db.add(Subscriber(email=normalised, source=source))
    try:
        db.commit()
    except IntegrityError:
        # A double-clicked form sends the same email twice, and both requests
        # can pass the read above before either commits. The unique index on
        # ``email`` keeps the second row out; uncaught, that surfaced as the
        # generic 409 "conflicts with one that already exists" from an endpoint
        # that promises duplicates are accepted. The other request subscribed
        # this address, so this one is the duplicate.
        db.rollback()
        return False
    return True


@router.post(
    "/subscribers",
    summary="Subscribe to GST filing deadline reminders",
    description=(
        "Accepts an email and subscribes it to GST filing reminders. "
        "Duplicate emails are accepted idempotently. Public — called from "
        "the tools pages before sign-in."
    ),
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_subscriber_limit)],
)
def subscribe(
    body: SubscriberRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    is_new = _upsert_subscriber(db, body.email, body.source)
    logger.info(
        "Subscriber %s",
        "added" if is_new else "already subscribed",
        extra={"email_domain": body.email.rsplit("@", 1)[-1], "source": body.source},
    )
    return {
        "subscribed": True,
        "new": is_new,
        "message": (
            "You'll receive reminders before each filing deadline."
            if is_new
            else "You're already subscribed."
        ),
    }


@router.get(
    "/subscribers/unsubscribe",
    summary="Unsubscribe from filing reminders",
    description=(
        "Validates the HMAC token and marks the email as unsubscribed. "
        "The token prevents anyone from unsubscribing an address they do "
        "not control."
    ),
    dependencies=[Depends(_subscriber_limit)],
)
def unsubscribe(
    email: str = Query(..., max_length=320),
    token: str = Query(..., min_length=64, max_length=64),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    expected = make_unsubscribe_token(email)
    # Bytes, not str: a non-ASCII token made compare_digest raise (a 500).
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return {"unsubscribed": False, "error": "Invalid or expired link."}

    normalised = email.lower().strip()
    subscriber = db.query(Subscriber).filter_by(email=normalised).first()
    if subscriber is None:
        return {"unsubscribed": False, "error": "Email not found."}

    if subscriber.unsubscribed_at is not None:
        return {"unsubscribed": True, "message": "Already unsubscribed."}

    subscriber.unsubscribed_at = utcnow()
    db.commit()
    logger.info(
        "Subscriber unsubscribed",
        extra={"email_domain": email.rsplit("@", 1)[-1]},
    )
    return {"unsubscribed": True, "message": "You've been unsubscribed."}
