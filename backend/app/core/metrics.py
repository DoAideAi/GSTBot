"""Request counts, error rates and latency, per hour, across every worker.

Before this the only record of how the API was doing was one log line per
request — enough to investigate a request, not to answer "is the error rate
up since the deploy?" without a log aggregator this box does not have.

Kept in Redis rather than in process: the API runs as several uvicorn
workers, and a counter in each would see only its own share of the traffic.
One hash per UTC hour, kept for two days. Recording is best effort — a
request never fails, or waits more than one pipeline round trip, because a
counter could not be written.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.redis_client import get_redis, mark_unavailable

KEY_PREFIX = "gstbot:metrics:"
# Which routes went over their budget that hour, as "METHOD /template" -> count.
# A separate hash so the per-hour row keeps a fixed set of fields.
OVER_PREFIX = KEY_PREFIX + "over:"
RETENTION = timedelta(hours=48)
SLOW_MS = 1000

FIELDS = (
    "requests",
    "status_2xx",
    "status_3xx",
    "status_4xx",
    "status_5xx",
    "slow",
    "over_budget",
    "latency_ms_sum",
)


def _hour(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%d%H")


def record(
    status_code: int,
    duration_ms: float,
    *,
    now: datetime | None = None,
    route: str | None = None,
    budget_ms: int | None = None,
) -> None:
    """Count one answered request. Never raises.

    *route* is ``"METHOD /template"`` and *budget_ms* its budget from
    :mod:`app.core.budgets`; a request over it is counted, and so is its route.
    """
    client = get_redis()
    if client is None:
        return
    hour = _hour(now or datetime.now(UTC))
    key = KEY_PREFIX + hour
    over = budget_ms is not None and duration_ms > budget_ms
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hincrby(key, "requests", 1)
        pipe.hincrby(key, f"status_{min(max(status_code // 100, 2), 5)}xx", 1)
        pipe.hincrbyfloat(key, "latency_ms_sum", float(duration_ms))
        if duration_ms >= SLOW_MS:
            pipe.hincrby(key, "slow", 1)
        if over:
            pipe.hincrby(key, "over_budget", 1)
            if route:
                pipe.hincrby(OVER_PREFIX + hour, route, 1)
                pipe.expire(OVER_PREFIX + hour, int(RETENTION.total_seconds()))
        pipe.expire(key, int(RETENTION.total_seconds()))
        pipe.execute()
    except Exception:  # noqa: BLE001 - a metric is never worth a failed request
        mark_unavailable("metrics write failed")


def _row(hour: datetime, raw: dict[Any, Any]) -> dict[str, Any]:
    values = {k.decode() if isinstance(k, bytes) else str(k): v for k, v in raw.items()}
    counts = {f: float(values.get(f, 0) or 0) for f in FIELDS}
    requests = int(counts["requests"])
    return {
        "hour": hour.strftime("%Y-%m-%dT%H:00Z"),
        "requests": requests,
        "status_2xx": int(counts["status_2xx"]),
        "status_3xx": int(counts["status_3xx"]),
        "status_4xx": int(counts["status_4xx"]),
        "status_5xx": int(counts["status_5xx"]),
        "slow": int(counts["slow"]),
        "over_budget": int(counts["over_budget"]),
        "error_rate": round(counts["status_5xx"] / requests, 4) if requests else 0.0,
        "avg_ms": round(counts["latency_ms_sum"] / requests, 1) if requests else 0.0,
    }


def summary(hours: int = 24, *, now: datetime | None = None) -> dict[str, Any] | None:
    """The last *hours* hours, oldest first, plus their totals; ``None`` without Redis."""
    client = get_redis()
    if client is None:
        return None
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    hours_list = [current - timedelta(hours=i) for i in range(hours - 1, -1, -1)]
    try:
        pipe = client.pipeline(transaction=False)
        for hour in hours_list:
            pipe.hgetall(KEY_PREFIX + _hour(hour))
        for hour in hours_list:
            pipe.hgetall(OVER_PREFIX + _hour(hour))
        fetched = pipe.execute()
        raws, overs = fetched[: len(hours_list)], fetched[len(hours_list):]
    except Exception:  # noqa: BLE001
        mark_unavailable("metrics read failed")
        return None
    rows = [_row(h, raw or {}) for h, raw in zip(hours_list, raws, strict=True)]
    total_requests = sum(r["requests"] for r in rows)
    total_5xx = sum(r["status_5xx"] for r in rows)
    weighted_ms = sum(r["avg_ms"] * r["requests"] for r in rows)
    by_route: dict[str, int] = {}
    for raw in overs:
        for name, count in (raw or {}).items():
            label = name.decode() if isinstance(name, bytes) else str(name)
            by_route[label] = by_route.get(label, 0) + int(float(count))
    return {
        "hours": rows,
        "totals": {
            "requests": total_requests,
            "status_4xx": sum(r["status_4xx"] for r in rows),
            "status_5xx": total_5xx,
            "slow": sum(r["slow"] for r in rows),
            "over_budget": sum(r["over_budget"] for r in rows),
            "error_rate": round(total_5xx / total_requests, 4) if total_requests else 0.0,
            "avg_ms": round(weighted_ms / total_requests, 1) if total_requests else 0.0,
        },
        # Worst first: the routes to look at, not every route that ran.
        "over_budget_routes": dict(
            sorted(by_route.items(), key=lambda item: (-item[1], item[0]))[:20]
        ),
    }
