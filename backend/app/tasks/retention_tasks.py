"""Daily pruning of personal data past its retention.

See ``app/services/retention.py``: the pruning also runs when feedback or a new
client error arrives, but a quiet site gets neither for weeks, and a retention
period that only applies when something else happens is not one.
"""
from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services import job_health, retention

logger = logging.getLogger(__name__)


@celery_app.task(
    name="retention.prune_personal_data",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
)
def prune_personal_data_task(self) -> dict:
    """Clear feedback sender addresses and client errors past their retention.

    Idempotent and daily, so a database that is down at the hour is retried
    twice and otherwise caught by tomorrow's run.
    """
    db = SessionLocal()
    try:
        result = retention.prune_personal_data(db).as_dict()
        logger.info("Personal data pruned", extra=result)
        job_health.record_heartbeat("personal-data-retention")
        return result
    except Exception as exc:  # noqa: BLE001 - retried, then surfaced
        db.rollback()
        logger.exception(
            "Personal data pruning failed",
            extra={"celery_task_id": self.request.id, "retry": self.request.retries},
        )
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
