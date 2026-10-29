"""A lazily-created, shared Redis client behind a circuit breaker.

Redis is a *soft* dependency here. It backs rate limiting and the Celery
broker, and the product is still able to accept and parse an invoice without
it — so nothing in this module raises on a dead server. Callers get ``None``
and fall back, and the health endpoint is what tells an operator it is down.

Degrading is the easy half. The hard half is the two things a naive memo gets
wrong, both of which turn a soft dependency back into a hard one:

*Coming back.* An outage remembered forever is an outage that outlives itself.
The API is ordered ``After=redis-server.service`` but does not require it, so
starting during a Redis restart is ordinary — and with a permanent memo that
process would rate-limit per-process and report ``degraded`` until someone
restarted it, long after Redis was healthy. So the memo is a *deadline*, and
the next caller past it re-probes.

*Dying mid-life.* A memo set only on the startup path does nothing about the
client that connected and then lost its server. That client stays cached and
every caller pays ``socket_connect_timeout`` plus ``socket_timeout`` before
falling back — on the global rate limit, which is in front of every request.
A 2s dependency times every request is an outage no matter which side of it is
called soft. So a caller that fails on a live client trips the same breaker
(``mark_unavailable``) and the rest of the cooldown skips Redis outright.

The cost of an outage is therefore one connection attempt per cooldown for the
whole process, whichever path discovers it, and recovery needs nobody.
"""
from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Any | None = None
# Monotonic deadline before which Redis is not retried. 0.0 means "closed" —
# monotonic, so a clock adjustment cannot strand the breaker open for hours.
_down_until: float = 0.0
# Whether the *current* outage has already been logged. One warning per outage
# rather than one per cooldown: this is a supported degraded mode, and a line
# every 30 seconds is how an operator learns to filter the channel out.
_reported: bool = False


def _now() -> float:
    """Indirection so tests can move the clock instead of sleeping through it."""
    return time.monotonic()


def _trip(reason: str) -> None:
    """Open the breaker: drop the client and stop trying for the cooldown."""
    global _client, _down_until, _reported

    _client = None
    _down_until = _now() + settings.redis_retry_interval_seconds
    if not _reported:
        logger.warning(
            "Redis unavailable, degrading gracefully (retrying in %ss): %s",
            settings.redis_retry_interval_seconds,
            reason,
        )
        _reported = True


def mark_unavailable(reason: object = "connection failed") -> None:
    """Trip the breaker from a caller that held a client and lost the server.

    ``get_redis`` only sees failures at connect time. This is how the failure
    that happens *later* — mid-pipeline, on a client that was fine a second ago
    — reaches the breaker, so the rest of the process stops paying a socket
    timeout per request for a server that is not there.
    """
    _trip(str(reason) or "connection failed")


def is_outage(exc: BaseException) -> bool:
    """Whether *exc* says the server is unreachable, rather than that one
    command or one value was wrong.

    Connection and timeout failures — redis's own, or the socket's — are the
    server going away, and the breaker exists for those. A ``ResponseError``
    (``WRONGTYPE``, a write refused at ``maxmemory``, a read-only replica) is a
    server that answered, and a decode or ``int()`` failure on what it returned
    is a bad value, not a dead connection.
    """
    try:
        import redis

        if isinstance(exc, (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)):
            return True
        if isinstance(exc, redis.exceptions.RedisError):
            return False
    except ImportError:  # pragma: no cover - redis is a hard install dependency
        pass
    return isinstance(exc, OSError)


def report_failure(exc: BaseException, what: str) -> None:
    """Route a failure from a caller holding the client: trip, or just log.

    Every caller used to trip the breaker on any exception. The breaker drops
    the shared client for the whole process for a cooldown — rate limiting
    falls back to per-worker counters, metrics and job health go dark — so one
    malformed value took Redis away from everything. The recent-lookups list
    made that permanent: a stale entry tripped it on every landing-page read,
    and with the breaker open no new lookup could be written to push the entry
    out. Only an outage trips it now; anything else is logged at ERROR with its
    class and message, which the one-per-outage breaker warning never carried.
    """
    if is_outage(exc):
        _trip(f"{what}: {type(exc).__name__}: {exc}")
        return
    logger.error("Redis %s failed: %s: %s", what, type(exc).__name__, exc)


def get_redis() -> Any | None:
    """The shared client, or ``None`` when Redis cannot be reached.

    Never raises, never blocks longer than one connect attempt, and attempts at
    most one connect per cooldown while the server is down.
    """
    global _client, _down_until, _reported

    if _client is not None:
        return _client
    if _now() < _down_until:
        return None

    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_timeout=settings.redis_timeout_seconds,
            health_check_interval=30,
            decode_responses=True,
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001 - any failure means "no Redis"
        _trip(f"{type(exc).__name__}: {exc}")
        return None

    if _reported:
        # The counterpart to the warning above. Without it the log says Redis
        # went away and never says it came back, which leaves whoever reads it
        # later unable to tell a resolved blip from an ongoing outage.
        logger.info("Redis reachable again")

    _client = client
    _down_until = 0.0
    _reported = False
    return _client


def ping() -> bool:
    """Whether Redis answers right now. Used by the health endpoint."""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001 - the caller's job is to report this
        # Health is usually the first caller to touch a server that died since
        # it was last used, so it is also the one that should trip the breaker
        # — otherwise the next request discovers it the expensive way.
        mark_unavailable(f"{type(exc).__name__}: {exc}")
        return False


def close() -> None:
    """Release the connection pool. Called on application shutdown.

    Without this the sockets stay open until the server times them out, which
    on a rolling restart means the old process's connections and the new one's
    are both counted against ``maxclients`` for a while.
    """
    global _client
    if _client is not None:
        # Closing an already-dead client raises; that is not a failure here.
        with contextlib.suppress(Exception):
            _client.close()
    _client = None


def reset() -> None:
    """Drop the cached client and the breaker state. For tests."""
    global _down_until, _reported
    close()
    _down_until = 0.0
    _reported = False
