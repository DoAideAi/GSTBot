"""Heartbeats for the scheduled jobs, and what the queue behind them looks like.

Beat has no page of its own: a missed nightly sweep is silent unless something
watches for it, which is what ``/health/jobs`` exists to do. Two different
signals, read from two different places:

* **Heartbeats.** Each scheduled task stamps a timestamp into Redis the
  moment it finishes — see :func:`record_heartbeat` — and this reports how
  long ago that was against how often the job is supposed to run. A beat
  process that stopped scheduling entirely leaves every heartbeat exactly as
  stale as the outage is long, which a worker-side check alone would never
  show: the workers themselves are fine, and nothing is telling them to do
  anything.
* **Queue depth.** How many messages are sitting in the broker's list right
  now, read directly off Redis rather than through Celery's ``inspect()`` —
  which asks the *workers*, not the broker, and answers nothing when no
  worker is up to reply. A queue backing up while every worker is dead is
  exactly the situation this exists to catch, and ``inspect`` is blind to it.

Every function here is best-effort and swallows its own failures: this module
exists to report on the health of other things, and a monitoring read must
never itself become the outage.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_HEARTBEAT_PREFIX = "gstbot:job_heartbeat:"
# When a worker first started watching for each job, written once (NX) at
# worker start. See :func:`watch_scheduled_jobs`.
_WATCHED_PREFIX = "gstbot:job_watched_since:"

# How often each scheduled job is supposed to run, named to match the keys in
# ``celery_app.celery_app.conf.beat_schedule``. Kept here rather than derived
# from that schedule because this has to be readable from a process that never
# imports Celery at all — which is exactly what the API process does the rest
# of the time; see :func:`worker_status` for the one place it does.
JOB_STALE_AFTER_SECONDS: dict[str, int] = {
    # Daily at 07:00 IST. Stale past 26h gives a two-hour margin over a run
    # that slipped, rather than waiting almost two full days to say so.
    "filing-deadline-sweep": 26 * 3600,
    "filing-deadline-alert-emails": 26 * 3600,
    # Hourly. Stale past 90 minutes covers a beat tick landing a little late
    # without waiting almost two full cycles to raise it.
    "stalled-parse-sweep": 90 * 60,
    # Daily at 02:45, with the same two-hour margin as the sweep.
    "personal-data-retention": 26 * 3600,
}


def record_heartbeat(job_name: str, *, at: datetime | None = None) -> None:
    """Stamp *job_name* as having just finished. Never raises.

    Called from the task itself, after its own work is already committed —
    see the tasks in :mod:`app.tasks.alert_tasks` and
    :mod:`app.tasks.invoice_tasks`. A heartbeat write that fails costs one
    missing data point on the health screen; it must never be allowed to
    undo work the task has already done.
    """
    client = get_redis()
    if client is None:
        return
    with contextlib.suppress(Exception):
        client.set(_HEARTBEAT_PREFIX + job_name, (at or datetime.now(UTC)).isoformat())


def watch_scheduled_jobs(*, at: datetime | None = None) -> None:
    """Note when watching began for any job not already being watched. Never raises.

    A job with no heartbeat was stale from the moment it was added: the
    release that added the daily retention job left /health/jobs "degraded",
    and the monitor reporting it every quarter hour, until its first 02:45
    run — a false alarm on every deploy that adds a job. Watching from the
    worker's start gives a new job one full period to report before silence
    counts against it; one that still never reports is flagged as before.
    Called from the worker's ready signal in :mod:`app.celery_app`.
    """
    client = get_redis()
    if client is None:
        return
    stamp = (at or datetime.now(UTC)).isoformat()
    with contextlib.suppress(Exception):
        for name in JOB_STALE_AFTER_SECONDS:
            client.set(_WATCHED_PREFIX + name, stamp, nx=True)


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    moment = datetime.fromisoformat(raw)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


@dataclass(frozen=True)
class JobStatus:
    """One scheduled job's last heartbeat, and whether it is overdue.

    ``stale`` is ``None`` when there is nothing to judge staleness against —
    Redis itself is unreachable, so "no heartbeat" cannot be told apart from
    "no way to check for one".
    """

    name: str
    last_run: datetime | None
    stale: bool | None


def job_statuses() -> list[JobStatus]:
    """Every scheduled job's last heartbeat, oldest-defined first."""
    client = get_redis()
    now = datetime.now(UTC)
    statuses: list[JobStatus] = []
    for name, stale_after in JOB_STALE_AFTER_SECONDS.items():
        last_run: datetime | None = None
        if client is not None:
            with contextlib.suppress(Exception):
                raw = client.get(_HEARTBEAT_PREFIX + name)
                if raw:
                    last_run = datetime.fromisoformat(raw)
                    # Stamped aware by record_heartbeat; a naive value (an older
                    # writer, a hand-set key) parsed fine and then raised on the
                    # subtraction below, outside this guard — a 500 from the
                    # health check monitoring polls. Naive means UTC here.
                    if last_run.tzinfo is None:
                        last_run = last_run.replace(tzinfo=UTC)

        stale: bool | None
        if last_run is not None:
            stale = (now - last_run).total_seconds() > stale_after
        elif client is not None:
            # Redis answers, but this job has never once reported in. Within
            # one period of a worker starting to watch for it, that is a job
            # whose first tick has not come yet; past it, or with no record of
            # watching at all, it is worth flagging rather than reading as
            # "fine, just quiet".
            watched_since: datetime | None = None
            with contextlib.suppress(Exception):
                watched_since = _parse(client.get(_WATCHED_PREFIX + name))
            stale = (
                watched_since is None
                or (now - watched_since).total_seconds() > stale_after
            )
        else:
            stale = None
        statuses.append(JobStatus(name=name, last_run=last_run, stale=stale))
    return statuses


# The default Celery queue. This product has never set ``task_routes``, so
# every task — the parse, the sweeps, the digest — lands in the one queue
# Celery names ``celery`` when nothing else is configured.
DEFAULT_QUEUE = "celery"


@dataclass(frozen=True)
class QueueStatus:
    reachable: bool
    depth: int | None
    error: str | None = None


def queue_status() -> QueueStatus:
    """How many messages are waiting in the broker, read directly off Redis.

    Deliberately not Celery's ``inspect().active_queues()``: that asks
    workers, and answers nothing when every worker is down — which is the one
    situation a backlog most needs to be caught in.
    """
    if not settings.celery_broker_url.startswith("redis"):
        return QueueStatus(reachable=False, depth=None, error="broker is not Redis")
    try:
        import redis

        client = redis.Redis.from_url(
            settings.celery_broker_url,
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_timeout=settings.redis_timeout_seconds,
        )
        depth = client.llen(DEFAULT_QUEUE)
        return QueueStatus(reachable=True, depth=int(depth))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        # The class to the public endpoint, the message to the log — as the
        # database and storage checks do. A broker's message names its host
        # and port, and ``/health/jobs`` answers anyone who asks.
        logger.warning("Broker queue depth check failed: %s", exc)
        return QueueStatus(reachable=False, depth=None, error=type(exc).__name__)


@dataclass(frozen=True)
class WorkerStatus:
    reachable: bool
    workers: list[str]
    error: str | None = None


def worker_status(timeout: float = 1.0) -> WorkerStatus:
    """Which workers answer a ping right now, within *timeout* seconds.

    Kept short on purpose: this runs inside a request a person is waiting on,
    and "nothing answered within a second" is itself the fact an operator
    needs — waiting out Celery's multi-second default for the same negative
    would make the health screen the slowest thing it reports on.
    """
    if not settings.celery_enabled:
        return WorkerStatus(reachable=False, workers=[], error="CELERY_ENABLED is off")
    try:
        from app.celery_app import celery_app

        replies = celery_app.control.inspect(timeout=timeout).ping() or {}
        return WorkerStatus(reachable=bool(replies), workers=sorted(replies))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        logger.warning("Worker ping failed: %s", exc)
        return WorkerStatus(reachable=False, workers=[], error=type(exc).__name__)
