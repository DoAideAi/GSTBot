"""One circuit breaker, whose probe cannot be lost.

The OpenRouter client (P33 M12) and the mail sender (P35 M12) each carried a
hand-written copy of the same breaker. In both, the probe let through after a
cooldown was released only by a call that went on to report success or
failure. Any other way out — the mail sender's "password is not ASCII" error
raises before either — left the probe flag set, and from then on the breaker
refused every call until the process restarted: mail, or the model, silently
off for good.
"""
from __future__ import annotations

import pytest

from app.core.breaker import Breaker


@pytest.fixture
def clock():
    return {"now": 1000.0}


@pytest.fixture
def breaker(clock):
    return Breaker("test", threshold=2, cooldown=60.0, clock=lambda: clock["now"])


def _trip(breaker):
    for _ in range(breaker.threshold):
        assert breaker.allow()
        with breaker.guard():
            breaker.failed()


def test_it_opens_after_the_threshold_and_refuses_for_the_cooldown(breaker, clock):
    _trip(breaker)
    assert not breaker.allow()
    clock["now"] += 59
    assert not breaker.allow()


def test_after_the_cooldown_it_lets_exactly_one_probe_through(breaker, clock):
    _trip(breaker)
    clock["now"] += 61
    assert breaker.allow()
    assert not breaker.allow()  # a second caller while the probe is out


def test_a_probe_that_reports_nothing_is_released_not_lost(breaker, clock):
    _trip(breaker)
    clock["now"] += 61
    assert breaker.allow()
    with pytest.raises(UnicodeError):
        with breaker.guard():
            raise UnicodeError("neither success nor failure")

    assert breaker.allow()  # the next caller can probe; the breaker is not wedged


def test_a_success_closes_it_and_a_failed_probe_reopens_it(breaker, clock):
    _trip(breaker)
    clock["now"] += 61
    assert breaker.allow()
    with breaker.guard():
        breaker.failed()
    assert not breaker.allow()

    clock["now"] += 61
    assert breaker.allow()
    with breaker.guard():
        breaker.succeeded()
    assert breaker.allow() and breaker.allow()


def test_both_clients_use_it():
    from app.services import email_sender, openrouter_client

    assert isinstance(email_sender.BREAKER, Breaker)
    assert isinstance(openrouter_client.BREAKER, Breaker)


def test_a_mail_probe_that_fails_on_a_non_ascii_password_does_not_wedge_mail(monkeypatch):
    from app.core.config import settings
    from app.services import email_sender
    from app.services.email_sender import EmailSendError, send_email

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_max_attempts", 1)
    now = {"t": 1000.0}
    monkeypatch.setattr(email_sender, "_monotonic", lambda: now["t"])
    calls = []

    def deliver(message):
        calls.append(1)
        raise answer[0]

    answer = [ConnectionRefusedError("refused")]
    monkeypatch.setattr(email_sender, "_deliver", deliver)
    for _ in range(email_sender.BREAKER_THRESHOLD):
        with pytest.raises(EmailSendError):
            send_email(to="a@example.com", subject="s", body="b")
    now["t"] += email_sender.BREAKER_COOLDOWN_SECONDS + 1

    answer[0] = UnicodeEncodeError("ascii", "£", 0, 1, "ordinal not in range")
    with pytest.raises(EmailSendError):
        send_email(to="a@example.com", subject="s", body="b")
    sent = len(calls)

    with pytest.raises(EmailSendError):
        send_email(to="a@example.com", subject="s", body="b")
    assert len(calls) == sent + 1  # tried again, not refused forever
