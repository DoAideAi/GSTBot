"""Sending one email over SMTP: the wiring, not the wording.

What the message says is :mod:`app.services.alert_delivery`'s concern; this
module is only about whether ``smtplib`` is driven correctly — TLS, login and
the timeout each only when configured to, and every failure it can raise
turned into one exception type the caller can catch without knowing which
underlying error smtplib produced.
"""
from __future__ import annotations

import logging
import smtplib

import pytest

from app.core.config import settings
from app.services import email_sender
from app.services.email_sender import EmailSendError, send_email

# The unpatched sleep, captured before the autouse fixture below can replace
# it. See test_the_backoff_is_actually_waited_out_and_not_merely_computed.
_REAL_SLEEP = email_sender._sleep


class _FakeSMTP:
    """Stands in for smtplib.SMTP, recording what was called on it."""

    instances: list[_FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def quit(self):
        self.quit_called = True

    def close(self):
        pass

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.sent = message


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    monkeypatch.setattr(settings, "smtp_from_address", "alerts@gst.doaide.com")
    monkeypatch.setattr(settings, "smtp_timeout_seconds", 10.0)
    # Pinned rather than left to the environment, so the retry assertions
    # below count attempts this file chose and not whatever a deployment set.
    monkeypatch.setattr(settings, "smtp_max_attempts", 3)
    monkeypatch.setattr(settings, "smtp_retry_max_wait_seconds", 15.0)
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    yield


@pytest.fixture(autouse=True)
def slept(monkeypatch) -> list[float]:
    """Every backoff delay, in order, without waiting any of them.

    Autouse because a transient failure now retries by default: without this
    the two failure tests that predate retrying would each spend three real
    seconds asleep proving something unrelated to timing.
    """
    delays: list[float] = []
    monkeypatch.setattr(email_sender, "_sleep", delays.append)
    return delays


def test_a_message_is_sent_with_the_configured_from_address():
    send_email(to="owner@example.com", subject="Test", body="Body text")

    client = _FakeSMTP.instances[0]
    assert client.host == "smtp.example.com"
    assert client.port == 587
    assert client.timeout == 10.0
    assert client.sent["To"] == "owner@example.com"
    assert client.sent["From"] == "alerts@gst.doaide.com"
    assert client.sent["Subject"] == "Test"
    assert client.sent.get_content().strip() == "Body text"


def test_tls_is_started_when_configured():
    send_email(to="owner@example.com", subject="s", body="b")

    assert _FakeSMTP.instances[0].started_tls is True


def test_tls_is_skipped_for_a_local_mail_catcher(monkeypatch):
    monkeypatch.setattr(settings, "smtp_use_tls", False)

    send_email(to="owner@example.com", subject="s", body="b")

    assert _FakeSMTP.instances[0].started_tls is False


def test_login_happens_only_when_a_username_is_configured(monkeypatch):
    send_email(to="owner@example.com", subject="s", body="b")
    assert _FakeSMTP.instances[0].logged_in is None

    monkeypatch.setattr(settings, "smtp_username", "relay-user")
    monkeypatch.setattr(settings, "smtp_password", "relay-pass")
    send_email(to="owner@example.com", subject="s", body="b")
    assert _FakeSMTP.instances[1].logged_in == ("relay-user", "relay-pass")


def test_an_smtp_error_becomes_an_email_send_error(monkeypatch):
    class _Refusing(_FakeSMTP):
        def send_message(self, message):
            raise smtplib.SMTPRecipientsRefused({"owner@example.com": (550, b"no such user")})

    monkeypatch.setattr(smtplib, "SMTP", _Refusing)

    with pytest.raises(EmailSendError):
        send_email(to="owner@example.com", subject="s", body="b")


def test_a_connection_failure_becomes_an_email_send_error(monkeypatch):
    class _Unreachable(_FakeSMTP):
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", _Unreachable)

    with pytest.raises(EmailSendError):
        send_email(to="owner@example.com", subject="s", body="b")


# ---------------------------------------------------------------------------
# Retrying the refusals that go away by themselves
# ---------------------------------------------------------------------------

class _FailsThenSends(_FakeSMTP):
    """Raises ``failures`` worth of ``error`` on connect, then behaves."""

    failures = 0
    error: Exception = smtplib.SMTPServerDisconnected("relay hung up")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if len(_FakeSMTP.instances) <= type(self).failures:
            raise type(self).error


def _relay(monkeypatch, *, failures: int, error: Exception) -> None:
    attempt = type("_Attempt", (_FailsThenSends,), {"failures": failures, "error": error})
    monkeypatch.setattr(smtplib, "SMTP", attempt)


class TestATransientRefusalIsRetried:
    """The digest carries filing deadlines, and a failed send waits a day.

    ``FAILED`` alerts stay sendable, so nothing is dropped — but the recovery
    already in place is tomorrow's run, and tomorrow is not a degraded
    delivery for an alert about a return due tomorrow.
    """

    def test_a_relay_that_hung_up_gets_asked_again(self, monkeypatch):
        _relay(monkeypatch, failures=1, error=smtplib.SMTPServerDisconnected("bye"))
        send_email(to="owner@example.com", subject="s", body="b")
        assert _FakeSMTP.instances[-1].sent is not None

    def test_a_4xx_is_smtps_transient_class_and_is_retried(self, monkeypatch):
        # The rule that is easiest to get backwards: SMTP's 4xx means "try
        # again later", the opposite way round to HTTP's.
        _relay(
            monkeypatch,
            failures=1,
            error=smtplib.SMTPResponseException(451, b"4.7.1 greylisted, retry"),
        )
        send_email(to="owner@example.com", subject="s", body="b")
        assert _FakeSMTP.instances[-1].sent is not None

    def test_a_relay_that_is_not_listening_yet_is_retried(self, monkeypatch):
        _relay(monkeypatch, failures=2, error=ConnectionRefusedError("refused"))
        send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 3

    def test_it_gives_up_after_the_configured_attempts(self, monkeypatch):
        monkeypatch.setattr(settings, "smtp_max_attempts", 3)
        _relay(monkeypatch, failures=99, error=smtplib.SMTPServerDisconnected("bye"))

        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 3

    def test_one_attempt_disables_retrying_entirely(self, monkeypatch):
        monkeypatch.setattr(settings, "smtp_max_attempts", 1)
        _relay(monkeypatch, failures=99, error=smtplib.SMTPServerDisconnected("bye"))

        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_the_error_raised_is_the_one_that_kept_happening(self, monkeypatch):
        """Not a generic "gave up" — the relay's own words are the only clue."""
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPResponseException(421, b"service not available"),
        )
        with pytest.raises(EmailSendError, match="service not available"):
            send_email(to="owner@example.com", subject="s", body="b")


class TestAPermanentRefusalIsNotRetried:
    """Asking twice turns a clear failure into a slow one."""

    def test_a_mailbox_that_does_not_exist_is_refused_once(self, monkeypatch):
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPRecipientsRefused({"owner@example.com": (550, b"no such user")}),
        )
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_a_rejected_password_is_not_offered_again(self, monkeypatch):
        """Repeating a bad login is how a relay decides to lock the account.

        It carries a code, so the 4xx/5xx rule already answers this without
        the class having to be named — which is the point: a 535 is permanent
        because it is a 5xx, not because somebody remembered to list it.
        """
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"),
        )
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_a_refusal_naming_no_reason_is_not_retried(self, monkeypatch):
        """``all()`` over an empty mapping is true, which would read as transient."""
        _relay(monkeypatch, failures=99, error=smtplib.SMTPRecipientsRefused({}))
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_one_permanent_address_among_deferred_ones_ends_it(self, monkeypatch):
        """The message cannot be delivered as addressed however often it is offered."""
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPRecipientsRefused(
                {"a@example.com": (451, b"deferred"), "b@example.com": (550, b"no such user")}
            ),
        )
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_an_unparseable_code_is_not_kept_asking(self, monkeypatch):
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPResponseException("not-a-code", b"confused relay"),
        )
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1

    def test_an_smtp_error_with_no_code_at_all_is_final(self, monkeypatch):
        _relay(monkeypatch, failures=99, error=smtplib.SMTPNotSupportedError("no STARTTLS"))
        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert len(_FakeSMTP.instances) == 1


class TestTheBackoffSchedule:

    def test_it_doubles_and_carries_jitter(self, monkeypatch, slept):
        monkeypatch.setattr(settings, "smtp_max_attempts", 4)
        _relay(monkeypatch, failures=99, error=smtplib.SMTPServerDisconnected("bye"))

        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")

        # 1s, 2s, 4s, each with up to half a second of jitter on top.
        assert len(slept) == 3
        assert 1.0 <= slept[0] < 1.5
        assert 2.0 <= slept[1] < 2.5
        assert 4.0 <= slept[2] < 4.5

    def test_jitter_keeps_concurrent_workers_from_re_colliding(self, monkeypatch):
        """A relay that rate-limited a burst must not get the burst back at once."""
        firsts = set()
        for _ in range(20):
            firsts.add(round(email_sender._BACKOFF_BASE_SECONDS + email_sender._jitter(), 6))
        assert len(firsts) > 1

    def test_a_wait_that_would_cross_the_budget_is_not_taken(self, monkeypatch, slept):
        """This cost is paid per recipient across every tenant in the run."""
        monkeypatch.setattr(settings, "smtp_max_attempts", 10)
        monkeypatch.setattr(settings, "smtp_retry_max_wait_seconds", 4.0)
        _relay(monkeypatch, failures=99, error=smtplib.SMTPServerDisconnected("bye"))

        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")

        # 1s and 2s fit; the third would take the total past four.
        assert len(slept) == 2
        assert sum(slept) <= 4.0

    def test_a_zero_budget_leaves_one_attempt_in_practice(self, monkeypatch, slept):
        monkeypatch.setattr(settings, "smtp_retry_max_wait_seconds", 0.0)
        _relay(monkeypatch, failures=99, error=smtplib.SMTPServerDisconnected("bye"))

        with pytest.raises(EmailSendError):
            send_email(to="owner@example.com", subject="s", body="b")
        assert slept == []
        assert len(_FakeSMTP.instances) == 1

    def test_a_send_that_succeeds_first_time_waits_for_nothing(self, slept):
        send_email(to="owner@example.com", subject="s", body="b")
        assert slept == []


def test_the_retried_send_is_the_same_message_not_a_rebuilt_one(monkeypatch):
    """A retry must not resend a half-built or differently-addressed message."""
    _relay(monkeypatch, failures=1, error=smtplib.SMTPServerDisconnected("bye"))
    send_email(to="owner@example.com", subject="Deadlines", body="Body text")

    delivered = _FakeSMTP.instances[-1].sent
    assert delivered["To"] == "owner@example.com"
    assert delivered["Subject"] == "Deadlines"
    assert delivered["From"] == "alerts@gst.doaide.com"
    assert delivered.get_content().strip() == "Body text"


def test_the_backoff_is_actually_waited_out_and_not_merely_computed():
    """Every other test in this file replaces ``_sleep`` with a recorder.

    That is what makes the schedule above assertable without a nine-second
    suite, and it also means none of those tests would notice if ``_sleep``
    stopped sleeping. An indirection that had lost its body — refactored to a
    ``pass``, or shadowed by a stub left behind — would keep all of them green
    while turning the retry loop into three immediate reconnections against a
    relay that has just rate-limited us, which is the burst the jitter and the
    doubling exist to prevent.

    So the one thing those tests cannot check is checked here directly, at a
    duration short enough to pay for. ``_REAL_SLEEP`` is bound at import, which
    happens before the autouse fixture can replace the module attribute —
    reading ``email_sender._sleep`` here would find the recorder instead and
    assert nothing at all.
    """
    import time

    before = time.perf_counter()
    _REAL_SLEEP(0.05)
    assert time.perf_counter() - before >= 0.04


# ---------------------------------------------------------------------------
# GB032: Observability — delivery success is logged
# ---------------------------------------------------------------------------

class TestDeliverySuccessIsLogged:

    def test_a_successful_send_logs_delivery(self, caplog):
        with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
            send_email(to="owner@example.com", subject="s", body="b")

        assert any(
            "Email delivered" in r.message and r.attempt == 1
            for r in caplog.records
        )

    def test_delivery_after_retry_logs_the_winning_attempt(self, monkeypatch, caplog):
        _relay(monkeypatch, failures=1, error=smtplib.SMTPServerDisconnected("bye"))

        with caplog.at_level(logging.INFO, logger="app.services.email_sender"):
            send_email(to="owner@example.com", subject="s", body="b")

        delivered = [r for r in caplog.records if "Email delivered" in r.message]
        assert len(delivered) == 1
        assert delivered[0].attempt == 2


class TestNoAddressReachesTheLog:
    """A refused recipient renders as ``{'owner@example.com': (450, ...)}``, and a
    4xx is retried — so the address was in the retry log line and in the error
    every caller logs. The log redacts by field name; message text never
    passes through that."""

    def test_the_retry_line_and_the_final_error_name_no_address(self, monkeypatch, caplog):
        _relay(
            monkeypatch,
            failures=99,
            error=smtplib.SMTPRecipientsRefused({"owner@example.com": (451, b"try later")}),
        )
        with (
            caplog.at_level(logging.INFO, logger="app.services.email_sender"),
            pytest.raises(EmailSendError) as raised,
        ):
            send_email(to="owner@example.com", subject="s", body="b")

        assert "owner@example.com" not in str(raised.value)
        assert "[address]" in str(raised.value)
        retries = [r.getMessage() for r in caplog.records if "retrying" in r.getMessage()]
        assert retries
        assert not any("owner@example.com" in line for line in retries)
        # The relay's code survives, which is the part worth reading.
        assert "451" in retries[0]


class TestANonAsciiCredential:
    """P23 M5: smtplib encodes the login as ASCII, so a password with a "£" in
    it raised UnicodeEncodeError on every send — not the EmailSendError this
    module promises — and its text names the password's character."""

    def test_it_is_a_permanent_send_error_that_does_not_quote_the_password(
        self, monkeypatch
    ):
        import smtplib

        from app.core.config import settings
        from app.services import email_sender

        monkeypatch.setattr(settings, "smtp_host", "relay.example.com")
        monkeypatch.setattr(settings, "smtp_username", "alerts")
        monkeypatch.setattr(settings, "smtp_password", "pa£s")
        attempts = []

        class Relay:
            def __init__(self, *a, **k):
                attempts.append(1)

            def quit(self):
                pass

            def starttls(self):
                pass

            def login(self, user, password):
                # What smtplib.SMTP.auth does with the credentials.
                f"\0{user}\0{password}".encode("ascii")

            def send_message(self, message):
                raise AssertionError("never reached")

        monkeypatch.setattr(smtplib, "SMTP", Relay)
        with pytest.raises(email_sender.EmailSendError) as caught:
            email_sender.send_email(to="owner@example.com", subject="s", body="b")
        assert len(attempts) == 1  # not retried: it cannot succeed
        assert "SMTP_PASSWORD" in str(caught.value)
        assert "£" not in str(caught.value) and caught.value.__cause__ is None


# ---------------------------------------------------------------------------
# The goodbye is not the send
# ---------------------------------------------------------------------------

class _QuitRefused(_FakeSMTP):
    """A relay that answers QUIT with 421, as the real ``quit()`` does by raising
    from the socket read or — under ``with`` — from ``__exit__``."""

    closed = False

    def quit(self):
        raise smtplib.SMTPResponseException(421, b"closing channel")

    def close(self):
        type(self).closed = True


class TestQuitDoesNotDecideTheSend:
    def test_a_refused_quit_after_delivery_is_not_a_failure_or_a_resend(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP", _QuitRefused)

        send_email(to="owner@example.com", subject="s", body="b")

        assert len(_FakeSMTP.instances) == 1  # sent once, not retried
        assert _FakeSMTP.instances[0].sent is not None
        assert _QuitRefused.closed  # the socket is still released

    def test_a_refused_quit_does_not_mask_a_permanent_refusal(self, monkeypatch):
        class _Rejects(_QuitRefused):
            def send_message(self, message):
                raise smtplib.SMTPDataError(550, b"message rejected")

        monkeypatch.setattr(smtplib, "SMTP", _Rejects)

        with pytest.raises(EmailSendError) as caught:
            send_email(to="owner@example.com", subject="s", body="b")
        assert "550" in str(caught.value)
        assert len(_FakeSMTP.instances) == 1  # permanent, so asked once

    def test_quit_is_sent_after_a_normal_delivery(self):
        send_email(to="owner@example.com", subject="s", body="b")
        assert _FakeSMTP.instances[0].quit_called


# ---------------------------------------------------------------------------
# The headers a receiving server checks before it reads a word
# ---------------------------------------------------------------------------

class TestTheMessageCarriesDateAndMessageId:
    """RFC 5322 requires Date; receivers such as Gmail reject or spam-file mail
    with no Message-ID. EmailMessage adds neither and smtplib does not either,
    so every digest left with Subject, From and To alone, and arrived only if
    the relay happened to patch them in.
    """

    def test_a_sent_message_has_a_date_and_a_message_id_on_the_sender_domain(self):
        from email.utils import parsedate_to_datetime

        send_email(to="owner@example.com", subject="s", body="b")

        sent = _FakeSMTP.instances[0].sent
        assert parsedate_to_datetime(sent["Date"]) is not None
        message_id = sent["Message-ID"]
        assert message_id.startswith("<") and message_id.endswith("@gst.doaide.com>")

    def test_a_retry_resends_the_same_message_id(self, monkeypatch):
        # One message, delivered at most once from the reader's point of view:
        # a receiver that already took an attempt drops the retry by its id.
        _relay(monkeypatch, failures=1, error=smtplib.SMTPServerDisconnected("bye"))

        send_email(to="owner@example.com", subject="s", body="b")

        attempts = [c for c in _FakeSMTP.instances if c.sent is not None]
        assert len(attempts) == 1
        # Fixed before the retry loop, so the attempt that succeeded carries the
        # id the failed one would have: present, and the message's only one.
        assert attempts[0].sent["Message-ID"]
        assert len(attempts[0].sent.get_all("Message-ID")) == 1

    def test_two_messages_have_different_ids(self):
        send_email(to="a@example.com", subject="s", body="b")
        send_email(to="b@example.com", subject="s", body="b")
        first, second = (c.sent["Message-ID"] for c in _FakeSMTP.instances)
        assert first != second


class TestPort465IsImplicitTLS:
    """P38 M5: SMTP_PORT=465 could be configured, and could never send.

    465 is the port most providers list for "SSL" (Zoho, Hostinger, Gmail's
    SSL option). A connection there is TLS from the first byte (RFC 8314).
    ``_deliver`` always opened plain SMTP and then asked for STARTTLS, so it
    waited for a greeting the server would never send in clear text. Every
    attempt ran out the timeout, every email failed, the breaker opened, and
    the configuration looked right. Port 465 now connects with SMTP_SSL and a
    verifying context, and every other port is unchanged.
    """

    class _FakeSMTPSSL(_FakeSMTP):
        def __init__(self, host, port, timeout=None, context=None):
            super().__init__(host, port, timeout=timeout)
            self.context = context

    @pytest.fixture()
    def ssl_fake(self, monkeypatch):
        monkeypatch.setattr(smtplib, "SMTP_SSL", self._FakeSMTPSSL)
        return self._FakeSMTPSSL

    def test_465_connects_over_tls_from_the_start(self, monkeypatch, ssl_fake):
        import ssl

        monkeypatch.setattr(settings, "smtp_port", 465)
        monkeypatch.setattr(settings, "smtp_username", "mailer")
        monkeypatch.setattr(settings, "smtp_password", "app-password")

        send_email(to="owner@example.com", subject="Hi", body="Body")

        (client,) = _FakeSMTP.instances
        assert isinstance(client, ssl_fake)
        assert client.port == 465 and not client.started_tls
        assert isinstance(client.context, ssl.SSLContext)
        assert client.context.verify_mode == ssl.CERT_REQUIRED
        assert client.logged_in == ("mailer", "app-password")
        assert client.sent is not None

    def test_587_still_upgrades_with_starttls(self, ssl_fake):
        send_email(to="owner@example.com", subject="Hi", body="Body")

        (client,) = _FakeSMTP.instances
        assert not isinstance(client, ssl_fake)
        assert client.started_tls
