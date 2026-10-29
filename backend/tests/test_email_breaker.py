"""A mail relay that is down is found out once, not once per recipient.

Every send retried a transient failure smtp_max_attempts times, each attempt
with its own connection timeout, and nothing carried the relay's state from
one send to the next. With the relay down, a reminder run over a thousand
subscribers paid that whole cost per address — tens of seconds each — until
the worker's time limit killed it, and its retry paid it all again; the alert
digest the same per business. After a run of sends that fail because the
relay is unreachable, sends fail at once for a cooldown — EmailSendError,
which every caller already handles — and one probe goes through after it.
"""
from __future__ import annotations

import smtplib

import pytest

from app.core.config import settings
from app.services import email_sender
from app.services.email_sender import EmailSendError, send_email


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_max_attempts", 1)
    monkeypatch.setattr(email_sender, "_sleep", lambda s: None)
    clock = {"now": 1000.0}
    monkeypatch.setattr(email_sender, "_monotonic", lambda: clock["now"])
    state = {"calls": 0, "raise": ConnectionRefusedError("refused"), "clock": clock}

    def deliver(message):
        state["calls"] += 1
        if state["raise"] is not None:
            raise state["raise"]

    monkeypatch.setattr(email_sender, "_deliver", deliver)
    return state


def _fail(times):
    for _ in range(times):
        with pytest.raises(EmailSendError):
            send_email(to="a@example.com", subject="s", body="b")


def test_after_a_run_of_unreachable_sends_it_stops_trying(relay):
    _fail(email_sender.BREAKER_THRESHOLD)
    calls = relay["calls"]

    with pytest.raises(EmailSendError, match="unavailable"):
        send_email(to="a@example.com", subject="s", body="b")

    assert relay["calls"] == calls


def test_one_probe_after_the_cooldown_and_a_delivery_closes_it(relay):
    _fail(email_sender.BREAKER_THRESHOLD)
    relay["clock"]["now"] += email_sender.BREAKER_COOLDOWN_SECONDS + 1
    relay["raise"] = None

    send_email(to="a@example.com", subject="s", body="b")
    send_email(to="b@example.com", subject="s", body="b")

    assert relay["calls"] == email_sender.BREAKER_THRESHOLD + 2


def test_a_refused_recipient_is_not_an_outage(relay):
    relay["raise"] = smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no such user")})
    _fail(email_sender.BREAKER_THRESHOLD + 2)
    assert relay["calls"] == email_sender.BREAKER_THRESHOLD + 2


def test_a_relay_that_answers_421_counts(relay):
    relay["raise"] = smtplib.SMTPResponseException(421, b"service not available")
    _fail(email_sender.BREAKER_THRESHOLD)
    calls = relay["calls"]
    with pytest.raises(EmailSendError, match="unavailable"):
        send_email(to="a@example.com", subject="s", body="b")
    assert relay["calls"] == calls
