"""Rate limiting: a fixed-window counter, in Redis when there is one.

Why a fixed window rather than a token bucket: the limits here exist to stop
one tenant burning a shared free-tier model quota or brute-forcing a password,
not to shape traffic to the millisecond. A fixed window is two Redis commands
and is exact about the thing that matters — "no more than N in any minute" —
whereas a leaky bucket costs a Lua script for a precision nobody here needs.

Every limit is keyed by *tenant*, not by connection. Behind a NAT, a whole
office shares one IP, and an IP-keyed upload limit would mean the first user in
the building spends everyone's quota. Authenticated callers are therefore keyed
on their user id and only anonymous ones fall back to the address.

With Redis down the limiter falls back to a per-process in-memory window. That
is deliberately weaker — four API processes means four times the limit — but a
weak limit that stays up beats a strong one that takes the API down with the
cache.

Note the absence of ``from __future__ import annotations`` here, unlike the
rest of the package. ``RateLimit`` is a *callable class*, and FastAPI resolves
string annotations against ``call.__globals__`` — which a class instance does
not have. With postponed evaluation on, ``__call__``'s ``request: Request``
stays an unresolved ForwardRef, FastAPI stops recognising it as the request,
and every rate-limited route sprouts a mandatory ``request`` query parameter.
Real annotations keep the dependency wired to the real Request.
"""

import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.ratespec import Rate, parse_rate
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

# Keeps the in-memory fallback from growing without bound under a flood of
# distinct keys. Oldest-touched entries are evicted first.
_MAX_MEMORY_KEYS = 10_000


# Every name a RATE_LIMIT_OVERRIDES entry can usefully target: each RateLimit
# registers itself, and a counter that reads the overrides directly (the
# per-account login and link budgets) registers its name beside its default.
# Startup checks the overrides against this, because a misspelt name is
# otherwise parsed, stored, and read by nothing.
_KNOWN_LIMITS: set[str] = {"global"}


def register_limit_name(name: str) -> str:
    """Declare *name* overridable, returning it for use as a constant."""
    _KNOWN_LIMITS.add(name)
    return name


def known_limit_names() -> frozenset[str]:
    return frozenset(_KNOWN_LIMITS)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class _MemoryWindows:
    """Process-local fixed windows. The fallback when Redis is unreachable."""

    def __init__(self) -> None:
        self._counts: OrderedDict[str, int] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, bucket_key: str) -> int:
        with self._lock:
            # The window start is part of the key, so a bucket is dead the
            # moment its window rolls over — but nothing deletes it. Evicting
            # the least-recently-touched quarter when the map gets large is
            # what bounds this; those are the rolled-over windows.
            if len(self._counts) > _MAX_MEMORY_KEYS:
                for key in list(self._counts)[: _MAX_MEMORY_KEYS // 4]:
                    self._counts.pop(key, None)
            count = self._counts.get(bucket_key, 0) + 1
            self._counts[bucket_key] = count
            self._counts.move_to_end(bucket_key)
            return count

    def peek(self, bucket_key: str) -> int:
        with self._lock:
            return self._counts.get(bucket_key, 0)

    def forget(self, bucket_key: str) -> None:
        with self._lock:
            self._counts.pop(bucket_key, None)

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()


_memory = _MemoryWindows()


# The clock the windows are cut against, named so a test can pin it.
#
# These are fixed windows aligned to the wall clock, not sliding ones, so where
# a test sits relative to a boundary changes its result: a burst that straddles
# one gets its budget silently refilled halfway through. That is invisible when
# the requests are fast and becomes a real flake when they are not — a login
# now pays a bcrypt round even for an address with no account, which is the
# point of that path, and it makes a twenty-five request burst take seconds.
# Pinning this is also the only way to assert what happens *at* a rollover
# without a test that sleeps for a minute.
_clock = time.time


def _bucket(rate: Rate) -> tuple[int, int]:
    """``(window_start, seconds_until_it_rolls)`` for the window now open."""
    now = _clock()
    window_start = int(now // rate.window) * rate.window
    # Rounded up, never down: this becomes Retry-After, and a client that
    # waits exactly that long has to land in the next window. Truncating said
    # 49 with 49.5 seconds left, so an obedient retry was refused again.
    return window_start, max(1, math.ceil(window_start + rate.window - now))


def charge(key: str, rate: Rate) -> Decision:
    """Count one request against *key* and decide whether it may proceed."""
    window_start, reset_in = _bucket(rate)
    bucket = f"ratelimit:{key}:{window_start}"

    count: int | None = None
    from app.core.redis_client import get_redis, report_failure

    client = get_redis()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(bucket, 1)
            pipe.expire(bucket, rate.window + 1)
            count = int(pipe.execute()[0])
        except Exception as exc:  # noqa: BLE001 - fall back, never fail the request
            logger.warning("Rate limiter degraded to in-process counters: %s", exc)
            # This runs in front of every request, so "catch it and carry on"
            # is not enough on its own: the client is cached and still dead, so
            # without tripping the breaker the *next* request pays the same
            # socket timeout, and so does every one after it. Reporting the
            # failure to the breaker is what turns a Redis outage into one slow
            # request per cooldown instead of every request being slow.
            report_failure(exc, "rate limit")
            count = None

    if count is None:
        count = _memory.hit(bucket)

    remaining = max(0, rate.limit - count)
    return Decision(
        allowed=count <= rate.limit,
        limit=rate.limit,
        remaining=remaining,
        retry_after=reset_in,
    )


# ``charge``, ``peek`` and ``forget`` are the three verbs a *failure* counter
# needs, as opposed to the request counter the ``RateLimit`` dependency
# implements. A request counter charges every call and asks afterwards whether
# that was one too many. A failure counter has to ask *before* doing the work
# (peek), charge only the attempts that failed, and — this is the part
# that matters — drop the count the moment the caller proves who they are
# (forget). Without ``forget``, counting failures per account hands anyone who
# knows an email address a way to lock its owner out by spending the budget on
# their behalf; with it, the lockout only ever reaches a caller who cannot
# produce the password either.


def peek(key: str, rate: Rate) -> Decision:
    """Read the count against *key* without charging for this call.

    ``allowed`` answers "is there budget for one more", so it goes false one
    attempt earlier than :func:`charge`'s — which answers "was the attempt just
    counted within budget". The two conventions differ because the callers do:
    this one is asked before the work, that one after.
    """
    window_start, reset_in = _bucket(rate)
    bucket = f"ratelimit:{key}:{window_start}"

    count: int | None = None
    from app.core.redis_client import get_redis, report_failure

    client = get_redis()
    if client is not None:
        try:
            raw = client.get(bucket)
            count = int(raw) if raw is not None else 0
        except Exception as exc:  # noqa: BLE001 - fall back, never fail the request
            logger.warning("Rate limiter degraded to in-process counters: %s", exc)
            report_failure(exc, "rate limit")
            count = None

    if count is None:
        count = _memory.peek(bucket)

    return Decision(
        allowed=count < rate.limit,
        limit=rate.limit,
        remaining=max(0, rate.limit - count),
        retry_after=reset_in,
    )


def forget(key: str, rate: Rate) -> None:
    """Drop *key*'s count for the window now open.

    Best effort on purpose: this is called after a caller has already been
    authenticated, and failing to clear a counter must never turn a successful
    login into an error. The worst case is that the count stands until the
    window rolls over on its own.

    Both stores are cleared, not whichever one is live. ``charge`` writes to
    Redis when it can and to memory when it cannot, so a Redis that flaps
    mid-window leaves attempts recorded in both places. Clearing only the one
    reachable right now would leave the other holding a count that no
    subsequent refund can reach — the user stays locked out until the window
    rolls, by a counter their correct password was supposed to have cleared.
    """
    window_start, _ = _bucket(rate)
    bucket = f"ratelimit:{key}:{window_start}"

    _memory.forget(bucket)

    from app.core.redis_client import get_redis, report_failure

    client = get_redis()
    if client is None:
        return
    try:
        client.delete(bucket)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("Could not clear rate-limit counter %s: %s", key, exc)
        report_failure(exc, "rate limit clear")


def client_ip(request: Request) -> str:
    """The caller's address, trusting proxy headers only when told to.

    ``X-Forwarded-For`` is a request header like any other: a client can send
    a fabricated one and mint itself a fresh rate-limit bucket per request. It
    is honoured only when ``TRUST_PROXY_HEADERS`` says a proxy we control is in
    front and is rewriting it.
    """
    if settings.trust_proxy_headers:
        # X-Real-IP first: deploy/caddy-gstbot.conf sets it from the
        # connection, overwriting whatever the client sent. X-Forwarded-For is
        # only safe left-most-first while the proxy also discards a client's
        # own value — Caddy does by default today, but that is a property of
        # its version and config, not of this code, and a client-written
        # left-most entry is a fresh rate-limit bucket per request.
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip[:64]
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Left-most entry is the original client; the rest are hops.
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def wait_phrase(seconds: int) -> str:
    """How long to wait, in the unit a person would say it in.

    Every limit here reports its wait in seconds, which reads fine for 45 and
    badly for 3600 — the hourly export limit answered "Try again in 3600s".
    Rounded up, so the advice never sends someone back early into a second
    refusal.
    """
    seconds = max(1, int(seconds))
    if seconds < 90:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds < 90 * 60:
        minutes = -(-seconds // 60)
        return f"{minutes} minutes"
    hours = -(-seconds // 3600)
    return f"{hours} hour{'s' if hours != 1 else ''}"


def identity(request: Request) -> str:
    """Who to charge this request to: ``user:<id>`` or ``ip:<addr>``.

    The token is decoded rather than looked up — the point is to attribute the
    request, and a signature check is enough for that without a database round
    trip on every call.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        subject = decode_access_token(header[7:].strip())
        if subject:
            return f"user:{subject}"
    return f"ip:{client_ip(request)}"


def apply_headers(response_headers: dict[str, str], decision: Decision) -> None:
    response_headers["X-RateLimit-Limit"] = str(decision.limit)
    response_headers["X-RateLimit-Remaining"] = str(decision.remaining)
    response_headers["X-RateLimit-Reset"] = str(decision.retry_after)


class RateLimit:
    """A FastAPI dependency enforcing one named limit.

    Used as ``dependencies=[Depends(RateLimit("uploads", "30/minute"))]``. The
    name is part of the key, so a caller's upload budget and their login budget
    are separate buckets rather than one shared pool.
    """

    def __init__(
        self, name: str, spec: str, *, by: str = "identity", detail: str | None = None
    ) -> None:
        # ``by``: "identity" (the signed-in user, else the address), "ip", or
        # "site" — one bucket shared by every caller, a ceiling on the total
        # rather than on any one of them. ``detail`` replaces the default
        # "try again in Ns" where the wait is hours, not seconds.
        self.name = register_limit_name(name)
        self.spec = spec
        self.by = by
        self.detail = detail
        self._rate: Rate | None = None

    @property
    def rate(self) -> Rate:
        # Parsed on first use rather than at import, so an override in settings
        # (and a monkeypatch in a test) is picked up.
        if self._rate is None:
            self._rate = parse_rate(settings.rate_limits.get(self.name, self.spec))
        return self._rate

    def __call__(self, request: Request) -> None:
        if not settings.rate_limit_enabled:
            return

        if self.by == "site":
            who = "site"
        elif self.by == "ip":
            who = f"ip:{client_ip(request)}"
        else:
            who = identity(request)
        decision = charge(f"{self.name}:{who}", self.rate)

        # Stashed on the request so the middleware can put the headers on the
        # response — a dependency has no response object to write to.
        request.state.rate_limit = decision

        if not decision.allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"limit_name": self.name, "limit": self.rate.label, "principal": who},
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=self.detail
                or f"Too many requests. Try again in {wait_phrase(decision.retry_after)}.",
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(decision.retry_after),
                },
            )


def check_global(request: Request) -> Decision | None:
    """The blanket per-caller limit every request passes through.

    Applied in middleware rather than as a dependency so that it also covers
    routes that do not exist — an unauthenticated scan for ``/admin.php`` is
    exactly the traffic a global limit is for.
    """
    if not settings.rate_limit_enabled:
        return None
    rate = parse_rate(settings.rate_limits.get("global", settings.rate_limit_default))
    return charge(f"global:{identity(request)}", rate)


def reset() -> None:
    """Forget every counter. For tests."""
    _memory.clear()
    from app.core.redis_client import get_redis

    client = get_redis()
    if client is None:
        return
    try:
        keys = list(client.scan_iter("ratelimit:*", count=500))
        if keys:
            client.delete(*keys)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("Could not clear rate-limit keys: %s", exc)
