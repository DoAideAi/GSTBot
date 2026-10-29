"""Celery application: the worker that parses invoices off the request path.

Kept in its own module rather than in ``main`` so the worker process never
imports FastAPI, and so ``celery -A app.celery_app worker`` is the whole
command.

The signal handlers at the bottom carry the request's correlation id across the
broker. Without them an upload's log lines stop at the enqueue and a separate,
unrelated id picks up in the worker — which is exactly where the interesting
failures happen, since the model call is on that side.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    before_task_publish,
    setup_logging,
    task_postrun,
    task_prerun,
    worker_shutdown,
)

from app.core.config import settings
from app.core.database import engine
from app.core.logging import (
    bind_correlation_id,
    configure_logging,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)
from app.core.redis_client import close as redis_close

celery_app = Celery(
    "gstbot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.invoice_tasks",
        "app.tasks.alert_tasks",
        "app.tasks.retention_tasks",
        "app.tasks.subscriber_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",  # Every deadline this product tracks is IST.
    enable_utc=True,
    task_track_started=True,
    # An invoice parse is one model call plus IO. Well under a minute in
    # practice; the hard limit is there so a hung upstream frees the worker.
    task_soft_time_limit=180,
    task_time_limit=240,
    # Free-tier models rate-limit, so a retry a minute later usually succeeds.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Explicit rather than inherited. Left unset, Celery falls back to
    # broker_connection_retry to decide whether to retry the *first* broker
    # connection, and 6.0 drops that fallback. The behaviour it decides is the
    # one that matters here: the unit is ordered After=redis-server.service but
    # does not require it, so a worker starting while Redis is still coming up
    # is ordinary, and the alternative to retrying is a unit that exits and
    # takes its five restarts before Redis has finished booting.
    broker_connection_retry_on_startup=True,
    # Recycle the child after this many tasks. Parsing runs pdf text extraction,
    # PIL, and tesseract in-process — C libraries whose arenas fragment rather
    # than return, so a worker that never recycles grows for as long as it runs
    # and is eventually OOM-killed mid-invoice.
    worker_max_tasks_per_child=settings.celery_max_tasks_per_child,
    # Deliberately *not* set: task_reject_on_worker_lost. It covers a narrower
    # case than acks_late does. Killing the whole worker drops the broker
    # connection, so the unacked message goes back on the queue either way; this
    # setting is only about a prefork *child* dying while the parent lives,
    # which is the OOM killer's usual choice because the child is the one
    # holding the decoded PDF. Requeueing there would put an invoice that
    # reliably exhausts memory back on the queue forever, since redelivery after
    # worker loss does not count against max_retries. Failing that one task is
    # the better of the two failures.
    #
    # "Failing" it is what the ``stalled-parse-sweep`` below is for, and the
    # reason it had to be added: a lost child runs no ``except`` block, so the
    # row it was holding stays in ``processing`` rather than reaching ``failed``.
    # This paragraph used to claim the invoice was left "visibly unparsed and
    # re-extractable from the UI", and neither half was true — ``processing``
    # renders as a neutral chip that means work in hand, and the dashboard's
    # needs-review count does not include it. The sweep is what makes the
    # sentence true.
    #
    # The three below bound what an upload pays when Redis is down, which is
    # the case the upload's inline-parse fallback exists for. Measured against
    # an unreachable broker before them: 19s on a refused port, before the
    # fallback even started, and no answer at all within two minutes on an
    # address that drops packets.
    #
    # Nothing reads a task's return value: every outcome is written to the
    # row, which is what the UI polls. Storing results anyway made each
    # ``delay()`` subscribe to the result backend first, and that subscription
    # retries twenty times before giving up — that was the 19s. Results also
    # sat in Redis for a day on a box where memory is the scarce thing.
    task_ignore_result=True,
    # redis-py's default connect timeout is none at all: a host that drops
    # packets holds the request thread until the kernel gives up. The same
    # bound the rate limiter's client uses. socket_timeout is more generous
    # because the worker's blocking pop shares it.
    broker_transport_options={
        "socket_connect_timeout": settings.redis_timeout_seconds,
        "socket_timeout": 10,
    },
    # One retry, quickly. Kombu's default is three with backoff, all of it
    # spent on the request thread; the fallback beyond it is parsing inline,
    # which the user is waiting for either way.
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.2,
    },
)

# The hour, in IST, at which the deadline sweep runs. Early enough that an alert
# raised this morning is seen on the day it is about, late enough that it is not
# competing with the nightly dump. ``timezone`` above is Asia/Kolkata and beat
# reads crontab entries in it, so this is 07:00 in India rather than 07:00 UTC —
# which would be half past noon there, after most of the working morning the
# alert exists to reach.
DEADLINE_SWEEP_HOUR = 7

# Minutes past DEADLINE_SWEEP_HOUR at which the day's alert emails go out.
# After the sweep, not alongside it: the sweep is what creates the rows this
# reads, and a beat schedule has no ordering guarantee between two entries at
# the same minute. Fifteen is comfortably longer than one tenant's sweep pass
# takes.
ALERT_EMAIL_MINUTE = 15

# Minute past each hour at which stranded parses are reaped. Offset from the
# top of the hour so it does not start alongside the deadline sweep, log
# rotation and everything else that fires at :00.
STALLED_SWEEP_MINUTE = 20
# Daily, in the quietest hour and clear of the 07:00 sweep.
RETENTION_HOUR = 2
RETENTION_MINUTE = 45
# Subscriber reminders, at 08:00 IST: after the account digests at 07:15, and
# in the morning of the working day the reminder is about.
SUBSCRIBER_REMINDER_HOUR = 8

celery_app.conf.beat_schedule = {
    # The first periodic task in this application, and the original reason
    # gstbot-beat.service exists. Daily rather than hourly because what it
    # produces is a date-based judgement that cannot change within a day: the
    # severities are derived from whole days remaining, so twenty-three of every
    # twenty-four runs would rewrite each row with the values it already had.
    #
    # A missed run is not made up. Beat has no catch-up here on purpose — a box
    # that was down overnight would otherwise fire the sweep on boot alongside
    # everything else it deferred, and the sweep is idempotent, so the run that
    # matters is simply tomorrow's.
    "filing-deadline-sweep": {
        "task": "alerts.sweep_filing_deadlines",
        "schedule": crontab(hour=DEADLINE_SWEEP_HOUR, minute=0),
    },
    # A no-op on any deployment that has not set ALERTS_EMAIL_ENABLED and
    # SMTP_HOST — see app/services/alert_delivery.py. Scheduled unconditionally
    # so turning email on is a config change, not a redeploy.
    "filing-deadline-alert-emails": {
        "task": "alerts.send_pending_emails",
        "schedule": crontab(hour=DEADLINE_SWEEP_HOUR, minute=ALERT_EMAIL_MINUTE),
    },
    # Hourly, and unlike the sweep above this one is not a date-based judgement
    # that can only change overnight — it is an operational state that a single
    # OOM kill creates at any moment, and the row is invisible on every screen
    # until this runs. Hourly is the smallest interval that is still comfortably
    # longer than ``invoice_parse_stall_seconds``, so a sweep never races a parse
    # that is merely slow.
    #
    # Cheap enough to run on a clock: one indexed query over a status that is
    # empty in the ordinary case, and it commits only when it found something.
    "stalled-parse-sweep": {
        "task": "invoices.reap_stalled",
        "schedule": crontab(minute=STALLED_SWEEP_MINUTE),
    },
    # Retention: feedback sender addresses and the client-error log, past 30
    # days. It also runs when new feedback or a new error arrives, but a quiet
    # site gets neither for weeks, and a retention period that only applies
    # when something else happens is not one. See app/services/retention.py.
    "personal-data-retention": {
        "task": "retention.prune_personal_data",
        "schedule": crontab(hour=RETENTION_HOUR, minute=RETENTION_MINUTE),
    },
    # The filing reminders the public site signs people up for, which nothing
    # sent. Daily; a no-op on any day that is not three days before a due
    # date, and wherever email is not configured.
    "subscriber-deadline-reminders": {
        "task": "subscribers.send_deadline_reminders",
        "schedule": crontab(hour=SUBSCRIBER_REMINDER_HOUR, minute=0),
    },
}

CORRELATION_HEADER = "correlation_id"


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    """Stop Celery installing its own handlers.

    Celery configures logging itself unless this signal has a receiver. Letting
    it do that would give the worker a different format from the API and drop
    the correlation id, so the receiver exists purely to take the decision back.
    """
    configure_logging(settings.log_level, settings.log_format)


@before_task_publish.connect
def _attach_correlation_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    """Stamp the publishing context's id onto the message.

    Protocol 2 puts unknown header keys on ``task.request`` in the worker, which
    is how the id survives the broker without changing any task signature. An id
    is generated when publishing from outside a request (a beat schedule, a
    shell) so the worker end is never anonymous.
    """
    if headers is None:
        return
    if not headers.get(CORRELATION_HEADER):
        headers[CORRELATION_HEADER] = get_correlation_id() or new_correlation_id()


@task_prerun.connect
def _bind_task_correlation_id(task: Any = None, **_: Any) -> None:
    request = getattr(task, "request", None)
    bind_correlation_id(getattr(request, CORRELATION_HEADER, None) if request else None)


@task_postrun.connect
def _clear_task_correlation_id(**_: Any) -> None:
    """Clear between tasks.

    A worker process is long-lived and reuses the context, so an id left bound
    would be inherited by the next task off the queue and attribute its lines to
    an unrelated upload.
    """
    set_correlation_id("")


@worker_shutdown.connect
def _release_pools(**_: Any) -> None:
    """Drop the database and Redis pools on the way out.

    The same reasoning as the API's lifespan teardown, and it matters more here:
    the worker unit allows TimeoutStopSec=300 so a long parse can finish, which
    is five minutes during which a redeployed worker's connections and the
    outgoing one's are both live. Tasks open their own sessions from the same
    module-level engine, so it is this process's pool that is holding them.

    Nothing here may raise. An exception out of a shutdown signal is a non-zero
    exit, which systemd records as a failed unit — turning an ordinary stop into
    something that looks like a crash.
    """
    logger = logging.getLogger(__name__)

    try:
        redis_close()
    except Exception as exc:  # noqa: BLE001 - shutdown is not a place to fail
        logger.warning("Redis client did not close cleanly: %s", exc)

    try:
        engine.dispose()
    except Exception as exc:  # noqa: BLE001 - shutdown is not a place to fail
        logger.warning("Database pool did not dispose cleanly: %s", exc)

    logger.info("Worker pools released")


logging.getLogger(__name__).debug("Celery configured with correlation propagation")
