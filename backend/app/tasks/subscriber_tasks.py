"""Daily filing-deadline reminders to the people who subscribed to them.

See ``app/services/subscriber_reminders.py``.
"""
from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services import job_health, subscriber_reminders

logger = logging.getLogger(__name__)


@celery_app.task(
    name="subscribers.send_deadline_reminders",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def send_deadline_reminders_task(self) -> dict:
    """Email active subscribers about the returns due in three days.

    Retried for the reason the alert digest is: an address the relay refuses
    is handled inside the service, so reaching here means the database was
    briefly unavailable. A retry resends to nobody already reached.
    """
    db = SessionLocal()
    try:
        result = subscriber_reminders.send_deadline_reminders(db).as_dict()
        job_health.record_heartbeat("subscriber-deadline-reminders")
        return result
    except Exception as exc:  # noqa: BLE001 - retried, then surfaced
        db.rollback()
        logger.exception(
            "Subscriber deadline reminders failed",
            extra={"celery_task_id": self.request.id, "retry": self.request.retries},
        )
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
