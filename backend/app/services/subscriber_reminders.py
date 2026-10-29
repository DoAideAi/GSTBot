"""Filing-deadline reminders for the people who subscribed to them.

The site collects addresses for "free email reminders before GSTR-1 and
GSTR-3B due dates" — the exit popup, the landing page, the due-dates page — and
carries a signed unsubscribe link for them. Nothing ever emailed a subscriber,
so every sign-up was a promise the product did not keep. This is the sender.

Run daily by beat. On a day that falls :data:`REMIND_DAYS_BEFORE` days before a
due date, every active subscriber gets one email naming the return, the period
and the date. Each send is committed as it happens (``last_reminded_for``), so
a retry or a second run the same day reaches nobody twice, and an address the
relay refused is tried again tomorrow-or-sooner rather than counted as told.

A no-op wherever ``ALERTS_EMAIL_ENABLED`` or ``SMTP_HOST`` is unset — the same
switch the alert digests use, since it is the same relay.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from urllib.parse import urlencode

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.gstr_return import ReturnType
from app.models.subscriber import Subscriber
from app.services import gst_calendar
from app.services.email_sender import EmailSendError, send_email

logger = logging.getLogger(__name__)

# Long enough to gather the figures and file without the late fee, short
# enough that the reminder is not forgotten before the day.
REMIND_DAYS_BEFORE = 3

_LABELS = {ReturnType.GSTR1: "GSTR-1", ReturnType.GSTR3B: "GSTR-3B"}


@dataclass(frozen=True)
class Reminded:
    sent: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _hmac_secret() -> str:
    return settings.subscriber_hmac_secret or settings.jwt_secret


def make_unsubscribe_token(email: str) -> str:
    """The token that proves an unsubscribe link was one this server sent."""
    return hmac.new(_hmac_secret().encode(), email.lower().encode(), hashlib.sha256).hexdigest()


def _signed_query(email: str) -> str:
    return urlencode({"email": email, "token": make_unsubscribe_token(email)})


def unsubscribe_url(email: str) -> str:
    """The API address a mailbox's one-click Unsubscribe button POSTs to."""
    return f"{settings.frontend_origin}/api/v1/subscribers/unsubscribe?{_signed_query(email)}"


def unsubscribe_page_url(email: str) -> str:
    """The page a person lands on from the link in the email's body.

    The body linked to the API itself, which answered a person with a raw
    JSON object. The page asks for a click before it unsubscribes anyone:
    mail scanners follow every link in a message, and one that acted on
    arrival would unsubscribe people who never opened the email.
    """
    return f"{settings.frontend_origin}/unsubscribe?{_signed_query(email)}"


def due_in(today: date, days: int = REMIND_DAYS_BEFORE) -> list[tuple[ReturnType, str, date]]:
    """The returns due exactly *days* from *today*: last month's, filed this month."""
    target = today + timedelta(days=days)
    period = gst_calendar.previous_period(gst_calendar.period_of(target))
    return [
        (return_type, period, due)
        for return_type in _LABELS
        if (due := gst_calendar.due_date(period, return_type)) == target
    ]


def _message(return_type: ReturnType, period: str, due: date, email: str) -> tuple[str, str, str]:
    label = _LABELS[return_type]
    month = date.fromisoformat(f"{period}-01").strftime("%B %Y")
    when = f"{due.day} {due.strftime('%b %Y')}"
    link = unsubscribe_page_url(email)
    subject = f"{label} for {month} is due on {when}"
    body = "\n".join([
        f"Your {label} for {month} is due on {when} — {REMIND_DAYS_BEFORE} days from today.",
        "",
        "Filing after the due date costs a late fee for every day it is late,",
        "and interest on any tax paid late.",
        "",
        f"Prepare it with DoAide GST: {settings.frontend_origin}/",
        "",
        "You are receiving this because you asked DoAide GST for filing reminders.",
        f"Unsubscribe: {link}",
    ])
    return subject, body, link


def send_deadline_reminders(db: Session, *, today: date | None = None) -> Reminded:
    """Email every active subscriber about the returns due in three days."""
    if not settings.alerts_email_enabled or not settings.smtp_host:
        return Reminded()
    sent = failed = 0
    for return_type, period, due in due_in(today or gst_calendar.today_ist()):
        key = f"{return_type.value}-{period}"
        subscribers = db.execute(
            select(Subscriber.id, Subscriber.email)
            .where(
                Subscriber.unsubscribed_at.is_(None),
                or_(Subscriber.last_reminded_for.is_(None), Subscriber.last_reminded_for != key),
            )
            .order_by(Subscriber.id)
        ).all()
        for subscriber_id, email in subscribers:
            subject, body, _page = _message(return_type, period, due, email)
            try:
                send_email(
                    to=email, subject=subject, body=body,
                    # RFC 8058 one-click, which Gmail and Yahoo require of
                    # bulk senders: the mailbox POSTs to this address itself.
                    headers={
                        "List-Unsubscribe": f"<{unsubscribe_url(email)}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
                )
            except EmailSendError:
                failed += 1
                logger.warning(
                    "Deadline reminder failed for a subscriber",
                    exc_info=True,
                    extra={"subscriber_id": subscriber_id, "reminder": key},
                )
                continue
            db.get(Subscriber, subscriber_id).last_reminded_for = key
            db.commit()
            sent += 1
        logger.info(
            "Deadline reminders sent", extra={"reminder": key, "sent": sent, "failed": failed}
        )
    return Reminded(sent=sent, failed=failed)
