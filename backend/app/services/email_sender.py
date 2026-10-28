"""Sending one plain-text email over SMTP — the one delivery channel this
product implements.

``app/services/alerting.py`` raises alert rows and says outright that nothing
reaches email, SMS or WhatsApp yet. This is the email half of that promise:
``smtplib`` against whatever relay ``SMTP_HOST`` names, with no template engine
and no queue of its own — the queue is Celery beat, and the caller decides what
"one message" means.

Kept to the standard library on purpose. A transactional-email provider's SDK
would mean a second set of credentials and a second failure mode to model, for
a volume — one digest per business per day — that plain SMTP handles without
noticing.

A refusal that would go away by itself is retried here, for the same reason
``openrouter_client`` retries one: the alternative is a materially worse
outcome, not merely a later one. The digest carries filing deadlines, a failed
send leaves the rows ``FAILED`` rather than dropping them, and ``FAILED`` is
still sendable — so the recovery already in place is *tomorrow's* run. On an
alert about a return due tomorrow, a day late is not a degraded delivery. A
relay that dropped the connection, is still starting up, or answered 4xx
because it is rate-limiting or greylisting this sender will take the same
message on the second attempt, seconds later.

Only transient refusals, though. SMTP's reply codes run the opposite way round
to HTTP's, and getting that backwards is how a retry loop becomes an outage:
**4xx is the transient one** ("try again later"), 5xx is permanent ("no such
mailbox", "authentication failed"). Asking twice about a mailbox that does not
exist turns a clear failure into a slow one, and repeating a rejected login is
how a relay decides to lock the account.
"""
from __future__ import annotations

import logging
import random
import re
import smtplib
import time
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    """The message could not be handed to the SMTP server."""


# The wait before the first retry. Doubles per attempt, so attempts land at
# roughly 1s, 2s, 4s. There is no ``Retry-After`` equivalent to honour: a 4xx
# reply is prose, and the delay some relays name in it is not a field.
_BACKOFF_BASE_SECONDS = 1.0



_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _without_addresses(exc: BaseException) -> str:
    """The relay's words with every email address taken out.

    ``SMTPRecipientsRefused`` renders as ``{'user@example.com': (450, ...)}``,
    and a 4xx refusal is retried — so the recipient's address went into the
    retry log line and into the error every caller logs. The log redacts by
    field name, which a message's own text never passes through.
    """
    return _ADDRESS.sub("[address]", str(exc))

def _sleep(seconds: float) -> None:
    """Indirection so tests can assert the schedule without living through it."""
    time.sleep(seconds)


def _jitter() -> float:
    """Spread retries so concurrent workers do not re-collide in lockstep.

    A relay that rate-limited a burst of digests would otherwise get the whole
    burst back at once, and rate-limit it again.
    """
    return random.uniform(0, 0.5)


def _is_transient(exc: Exception) -> bool:
    """Whether asking the same relay again could plausibly get a different answer.

    Classified by what smtplib actually raises rather than by the exception's
    name, because the two disagree in both directions:

    * :class:`~smtplib.SMTPAuthenticationError` and
      :class:`~smtplib.SMTPSenderRefused` are response exceptions carrying a
      code, so the 4xx/5xx rule already decides them correctly — a 535 bad
      password is permanent without needing to be named here.
    * :class:`~smtplib.SMTPServerDisconnected` carries no code at all. It is
      the relay hanging up mid-conversation, which is the most retryable
      failure there is, and a rule that only read codes would call it final.
    * :class:`~smtplib.SMTPRecipientsRefused` carries one code *per address*
      and is not a response exception. It is transient only if every address
      was deferred; one permanent rejection in the set means this message will
      not be delivered as addressed however many times it is offered.
    """
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return True
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        refusals = (exc.recipients or {}).values()
        # An empty mapping is not "every code was transient" — it is a refusal
        # that named no reason, and ``all()`` would call it retryable.
        return bool(refusals) and all(_transient_code(code) for code, _ in refusals)
    if isinstance(exc, smtplib.SMTPResponseException):
        return _transient_code(exc.smtp_code)
    if isinstance(exc, smtplib.SMTPException):
        # Everything smtplib defines that reaches here carries neither a code
        # nor a per-address one: ``SMTPNotSupportedError`` for a relay that
        # will not do STARTTLS, and the bare base class. None of them is about
        # a busy moment, so none is worth a second ask.
        #
        # Checked *before* the OSError line below and not merged into it,
        # because ``smtplib.SMTPException`` is itself a subclass of
        # ``OSError``. Without this branch that line answers True for every
        # SMTP failure that got this far, and the two classifications above
        # decide nothing — a 550 to a mailbox that does not exist would be
        # retried by the fallback after the code rule had already refused it.
        return False
    # Connection refused, DNS failure, a socket timeout: the network or a relay
    # that is not listening yet, neither of which is about this message.
    return isinstance(exc, OSError)


def _transient_code(code: object) -> bool:
    """True for SMTP's 4xx, the *temporary* negative completion class."""
    try:
        return 400 <= int(code) < 500  # type: ignore[arg-type]
    except (TypeError, ValueError):
        # A relay that answered something unparseable is not one to keep asking.
        return False


def _deliver(message: EmailMessage) -> None:
    """One attempt: connect, upgrade, authenticate, send. Raises smtplib's own."""
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


def send_email(*, to: str, subject: str, body: str) -> None:
    """Send one plain-text email, or raise :class:`EmailSendError`.

    Raises rather than returning a bool because the caller is a delivery loop
    over several alert rows, and it is the caller — not this function — that
    knows whether one recipient failing among several means the business was
    told or means the whole digest goes back on tomorrow's list.

    Synchronous and blocking. Every caller of this runs inside a Celery task
    rather than a request, so there is nothing here an event loop would help
    with, and a blocking call is one with a straightforward timeout: connecting,
    the handshake and the send all share :data:`Settings.smtp_timeout_seconds`
    through the socket itself, which is what stops one unreachable relay from
    holding a worker for the length of its default OS-level timeout.

    A transient refusal is retried up to :data:`Settings.smtp_max_attempts`
    times; see the module docstring for which refusals those are. The
    exception raised after the last one is the failure that kept happening,
    not a generic "gave up", so the log line names the relay's own words.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = to
    message.set_content(body)

    attempts = max(1, settings.smtp_max_attempts)
    budget = settings.smtp_retry_max_wait_seconds
    waited = 0.0

    # No exit arc to cover: ``attempts`` is at least 1, and the last iteration
    # either returns or raises — ``attempt == attempts`` is the first half of
    # the refusal below. Falling out of this loop would be a silent success on
    # a message that was never delivered, which is why it cannot be written to.
    for attempt in range(1, attempts + 1):  # pragma: no branch
        try:
            _deliver(message)
        except (smtplib.SMTPException, OSError) as exc:
            failure = EmailSendError(
                f"email delivery failed after {attempt} attempt(s): {_without_addresses(exc)}"
            )
            failure.__cause__ = exc
            if attempt == attempts or not _is_transient(exc):
                raise failure from exc

            delay = _BACKOFF_BASE_SECONDS * 2 ** (attempt - 1) + _jitter()
            if waited + delay > budget:
                # Sleeping out the rest of the budget to ask a relay that is
                # still refusing helps nobody, and this cost is paid once per
                # recipient across every tenant. Failing now leaves the rows
                # ``FAILED``, which tomorrow's run picks back up.
                logger.warning(
                    "SMTP retry budget exceeded, giving up after attempt %s of %s",
                    attempt,
                    attempts,
                    extra={
                        "attempt": attempt,
                        "attempts": attempts,
                        "waited_seconds": round(waited, 2),
                        "budget_seconds": budget,
                    },
                )
                raise failure from exc

            logger.info(
                "SMTP attempt %s of %s failed, retrying in %.1fs: %s",
                attempt,
                attempts,
                delay,
                _without_addresses(exc),
                extra={"attempt": attempt, "attempts": attempts},
            )
            _sleep(delay)
            waited += delay
        else:
            logger.info(
                "Email delivered",
                extra={"attempt": attempt, "attempts": attempts},
            )
            return
