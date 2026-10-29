"""Request counts, error rates, latency and business outcomes, per hour, across every worker.

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

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.redis_client import get_redis, report_failure

KEY_PREFIX = "gstbot:metrics:"
# Which routes went over their budget that hour, as "METHOD /template" -> count.
# A separate hash so the per-hour row keeps a fixed set of fields.
OVER_PREFIX = KEY_PREFIX + "over:"
EVENTS_PREFIX = KEY_PREFIX + "events:"
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


# Business outcomes counted beside the requests. A fixed set, so a caller
# cannot grow the hash with names nobody reads; ``count`` refuses the rest.
EVENTS = (
    "invoice_parsed",
    # Parsed, but by the regex heuristics rather than the model: the rate at
    # which the provider is failing, which an invoice that still parses hides.
    "invoice_parsed_heuristic",
    "invoice_duplicate",
    "invoice_parse_failed",
    "invoice_parse_stalled",
    # An edit or a delete landed while the model was reading, so the
    # extraction was thrown away. It was missing here, and ``count`` raises on
    # an unknown name: every one of these was logged as "failed to parse",
    # with a traceback, and counted as invoice_parse_failed.
    "invoice_parse_superseded",
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
    except Exception as exc:  # noqa: BLE001 - a metric is never worth a failed request
        report_failure(exc, "metrics write")


def count(event: str, n: int = 1, *, now: datetime | None = None) -> None:
    """Count *n* of a business outcome in its hour. Never raises.

    The request counters say the API answered; they cannot say a parse that
    answered 200 came back ``failed``, or that the model has quietly stopped
    being the thing that reads invoices. These can.
    """
    if event not in EVENTS:
        raise ValueError(f"unknown metrics event {event!r}")
    client = get_redis()
    if client is None:
        return
    key = EVENTS_PREFIX + _hour(now or datetime.now(UTC))
    try:
        pipe = client.pipeline(transaction=False)
        pipe.hincrby(key, event, n)
        pipe.expire(key, int(RETENTION.total_seconds()))
        pipe.execute()
    except Exception as exc:  # noqa: BLE001 - a metric is never worth a failed parse
        report_failure(exc, "metrics write")


def _number(value: Any) -> float:
    """A counter read back from Redis, or 0 when it is not one.

    Every field is written by HINCRBY/HINCRBYFLOAT, so this is about a value
    that got there some other way: a non-number made ``float()`` raise and the
    whole metrics endpoint answer 500, hiding the hours that were fine.
    """
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _row(hour: datetime, raw: dict[Any, Any]) -> dict[str, Any]:
    values = {k.decode() if isinstance(k, bytes) else str(k): v for k, v in raw.items()}
    counts = {f: _number(values.get(f, 0)) for f in FIELDS}
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
        for hour in hours_list:
            pipe.hgetall(EVENTS_PREFIX + _hour(hour))
        fetched = pipe.execute()
        n = len(hours_list)
        raws, overs, event_raws = fetched[:n], fetched[n : 2 * n], fetched[2 * n :]
    except Exception as exc:  # noqa: BLE001 - no summary, never a 500
        report_failure(exc, "metrics read")
        return None
    rows = [_row(h, raw or {}) for h, raw in zip(hours_list, raws, strict=True)]
    total_requests = sum(r["requests"] for r in rows)
    total_5xx = sum(r["status_5xx"] for r in rows)
    weighted_ms = sum(r["avg_ms"] * r["requests"] for r in rows)
    by_route: dict[str, int] = {}
    for raw in overs:
        for name, count in (raw or {}).items():
            label = name.decode() if isinstance(name, bytes) else str(name)
            by_route[label] = by_route.get(label, 0) + int(_number(count))
    events = dict.fromkeys(EVENTS, 0)
    for raw in event_raws:
        for name, value in (raw or {}).items():
            label = name.decode() if isinstance(name, bytes) else str(name)
            if label in events:
                events[label] += int(_number(value))
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
        "events": events,
    }
