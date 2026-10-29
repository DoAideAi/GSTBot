"""Filing-deadline reminders reach the people who subscribed to them.

The site collects addresses for "free email reminders before GSTR-1 and
GSTR-3B due dates" — the exit popup, the landing page, the due-dates page —
and has a signed unsubscribe link for them. Nothing ever emailed a
subscriber: every sign-up was a promise the product did not keep.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import settings
from app.models.subscriber import Subscriber
from app.services import subscriber_reminders
from app.services.email_sender import EmailSendError

# The GSTR-1 for September 2026 is due on 11 October; three days before.
GSTR1_EVE = date(2026, 10, 8)
GSTR3B_EVE = date(2026, 10, 17)


@pytest.fixture
def email_on(monkeypatch):
    monkeypatch.setattr(settings, "alerts_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    def fake_send(*, to, subject, body, headers=None):
        sent.append({"to": to, "subject": subject, "body": body, "headers": headers or {}})

    monkeypatch.setattr(subscriber_reminders, "send_email", fake_send)
    return sent


def _subscribe(db_session, *emails, unsubscribed=()):
    from app.models.mixins import utcnow

    for email in emails:
        db_session.add(Subscriber(email=email, source="landing"))
    for email in unsubscribed:
        db_session.add(Subscriber(email=email, source="landing", unsubscribed_at=utcnow()))
    db_session.commit()


def test_every_active_subscriber_hears_about_the_gstr1_due_in_three_days(
    db_session, email_on, outbox
):
    _subscribe(db_session, "a@example.com", "b@example.com", unsubscribed=["gone@example.com"])

    result = subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    assert sorted(m["to"] for m in outbox) == ["a@example.com", "b@example.com"]
    assert result.sent == 2
    message = outbox[0]
    assert "GSTR-1" in message["subject"] and "11 Oct 2026" in message["subject"]
    assert "September 2026" in message["body"]


def test_gstr3b_has_its_own_day(db_session, email_on, outbox):
    _subscribe(db_session, "a@example.com")

    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR3B_EVE)

    assert len(outbox) == 1 and "GSTR-3B" in outbox[0]["subject"]


def test_nothing_goes_out_on_a_day_with_no_deadline_three_days_off(db_session, email_on, outbox):
    _subscribe(db_session, "a@example.com")

    result = subscriber_reminders.send_deadline_reminders(db_session, today=date(2026, 10, 1))

    assert outbox == [] and result.sent == 0


def test_a_second_run_the_same_day_sends_nobody_the_same_reminder_twice(
    db_session, email_on, outbox
):
    # A retry, a beat that fired twice, a worker restarted mid-run.
    _subscribe(db_session, "a@example.com")
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    assert len(outbox) == 1


def test_the_next_deadline_is_still_sent(db_session, email_on, outbox):
    _subscribe(db_session, "a@example.com")
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR3B_EVE)

    assert [("GSTR-1" in m["subject"], "GSTR-3B" in m["subject"]) for m in outbox] == [
        (True, False),
        (False, True),
    ]


def test_each_email_carries_a_one_click_unsubscribe(db_session, email_on, outbox, client):
    """P34 M10: RFC 8058, which Gmail and Yahoo require of bulk senders.

    The header named the API's GET and nothing more, so a mailbox's
    "Unsubscribe" button could only open it in a browser — where it, like the
    link in the body, showed the subscriber a raw JSON object.
    """
    _subscribe(db_session, "a@example.com")
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    headers = outbox[0]["headers"]
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    header = headers["List-Unsubscribe"]
    assert header.startswith("<http") and header.endswith(">")
    parts = urlsplit(header[1:-1])
    assert parts.path == "/api/v1/subscribers/unsubscribe"

    # What the mailbox does: POST to it, with the one-click body, no cookies.
    response = client.post(
        parts.path + "?" + parts.query,
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 200
    assert response.json()["unsubscribed"] is True
    db_session.expire_all()
    assert db_session.query(Subscriber).one().unsubscribed_at is not None


def test_the_link_in_the_body_opens_a_page_not_the_api(db_session, email_on, outbox):
    _subscribe(db_session, "a@example.com")
    subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    link = next(w for w in outbox[0]["body"].split() if "unsubscribe" in w)
    parts = urlsplit(link)
    assert parts.path == "/unsubscribe"
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert params["email"] == "a@example.com" and len(params["token"]) == 64


def test_a_one_click_with_a_forged_token_unsubscribes_nobody(db_session, client):
    _subscribe(db_session, "a@example.com")

    response = client.post(
        "/api/v1/subscribers/unsubscribe",
        params={"email": "a@example.com", "token": "0" * 64},
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.json()["unsubscribed"] is False
    db_session.expire_all()
    assert db_session.query(Subscriber).one().unsubscribed_at is None


def test_it_does_nothing_where_email_is_not_configured(db_session, outbox, monkeypatch):
    monkeypatch.setattr(settings, "alerts_email_enabled", False)
    _subscribe(db_session, "a@example.com")

    result = subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    assert outbox == [] and result.sent == 0


def test_one_failed_address_neither_stops_the_rest_nor_counts_as_reminded(
    db_session, email_on, monkeypatch
):
    sent = []

    def flaky(*, to, subject, body, headers=None):
        if to == "bad@example.com":
            raise EmailSendError("550 no such user")
        sent.append(to)

    monkeypatch.setattr(subscriber_reminders, "send_email", flaky)
    _subscribe(db_session, "bad@example.com", "good@example.com")

    result = subscriber_reminders.send_deadline_reminders(db_session, today=GSTR1_EVE)

    assert sent == ["good@example.com"]
    assert (result.sent, result.failed) == (1, 1)
    bad = db_session.query(Subscriber).filter_by(email="bad@example.com").one()
    assert bad.last_reminded_for is None


def test_it_is_scheduled_and_watched():
    from app.celery_app import celery_app
    from app.services.job_health import JOB_STALE_AFTER_SECONDS

    entry = celery_app.conf.beat_schedule["subscriber-deadline-reminders"]
    assert entry["task"] == "subscribers.send_deadline_reminders"
    assert "subscriber-deadline-reminders" in JOB_STALE_AFTER_SECONDS
    assert "app.tasks.subscriber_tasks" in celery_app.conf.include
