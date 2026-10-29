"""How long personal data is kept, and the pruning that keeps to it.

Two things here outlive their use: the address a feedback message was sent
from, and the client-error log a public endpoint fills. Both were pruned only
"on the write" — when the next feedback or the next new error arrived — so on
a quiet site, which is most days, nothing was ever cleared and a 30-day policy
held addresses indefinitely. The same pruning now also runs daily from beat
(``app/tasks/retention_tasks.py``), whatever does or does not arrive.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.models.feedback import ClientError, Feedback
from app.models.mixins import utcnow

# How long an error that has stopped happening stays in the log. The table is
# deduplicated by page and message, but a public endpoint can still be sent
# endless distinct messages; without an end, those rows are kept forever.
CLIENT_ERROR_RETENTION = timedelta(days=30)
# How long a feedback row keeps the address it was sent from. The address is
# for spotting a flood or an abusive sender while it is happening; a year on it
# answers no question anyone has, and is a visitor's location kept beside their
# email and their own words. The message itself is kept — it is the point.
FEEDBACK_IP_RETENTION = timedelta(days=30)


@dataclass(frozen=True)
class Pruned:
    feedback_ips_cleared: int
    client_errors_deleted: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def clear_old_feedback_ips(db: Session, *, now: datetime | None = None) -> int:
    """Drop the sender address from feedback older than the retention. Not committed."""
    return db.execute(
        update(Feedback)
        .where(
            Feedback.created_at < (now or utcnow()) - FEEDBACK_IP_RETENTION,
            Feedback.ip_address.is_not(None),
        )
        .values(ip_address=None)
        .execution_options(synchronize_session=False)
    ).rowcount


def delete_old_client_errors(db: Session, *, now: datetime | None = None) -> int:
    """Delete client errors not seen within the retention. Not committed."""
    return db.execute(
        delete(ClientError).where(
            ClientError.last_seen_at < (now or utcnow()) - CLIENT_ERROR_RETENTION
        )
    ).rowcount


def prune_personal_data(db: Session, *, now: datetime | None = None) -> Pruned:
    """Both prunes, committed together."""
    result = Pruned(
        feedback_ips_cleared=clear_old_feedback_ips(db, now=now),
        client_errors_deleted=delete_old_client_errors(db, now=now),
    )
    db.commit()
    return result
