"""Emailing the alerts the daily sweep raises.

``app/services/alerting.py`` creates and refreshes ``Alert`` rows and says
plainly what it does not do: reach email, SMS or WhatsApp. ``channel`` and
``sent_at`` stay null on every row until something picks them up. This module
is that something, for email — the one channel :data:`Settings.smtp_host`
makes possible without a second integration.

**One email per business, not one per alert.** A business with three deadlines
approaching at once should see one message, not three — the sweep's own
central rule is not becoming noise, and a digest is the same rule applied to
delivery. Every alert folded into a digest still gets its own ``channel`` and
``sent_at`` stamped individually, so the per-row bookkeeping the sweep's
comment promised is intact; only the transmission is batched.

**What is sendable.** Only ``PENDING`` and ``FAILED`` — an alert already
``READ`` or ``DISMISSED`` means the business has already seen it, in the
product, and an email repeating that is exactly the noise the sweep exists to
avoid. ``FAILED`` stays sendable so a relay outage on one day is retried the
next, without a second sweep having to notice and re-raise anything.

**Isolation.** Committed per business, for the same reason the sweep itself
is: a bad address or a mid-run SMTP outage on one tenant must not cost every
tenant after it its place in today's send.

That is a property of the *writes*, and only of the writes. Every read this
module does — the tenant ids, their recipients, their alerts — happens up
front, across all tenants at once, because a read failing is a failure of the
whole run whichever loop it sits in; there is no tenant to isolate it from.
What the batching has to respect is the commit: it expires every ORM instance
in the session, so anything read before the loop must be plain rows rather
than mapped objects, or the first commit turns the saving back into a
per-instance re-read. Both prefetches obey that, and the loop writes through
``update()`` by id rather than by attribute for the same reason.
"""
from __future__ import annotations

import logging
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Row, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.alert import Alert, AlertStatus
from app.models.business import Business
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.user import User
from app.services.email_sender import EmailSendError, send_email

logger = logging.getLogger(__name__)

_CHANNEL = "email"

# READ and DISMISSED are excluded because the business already knows; RESOLVED
# because the thing the alert was about is no longer true. See the module
# docstring for why FAILED stays in rather than being given up on.
_SENDABLE_STATUSES = (AlertStatus.PENDING, AlertStatus.FAILED)

# How many tenant ids one ``IN`` may carry. Matches
# ``reconciliation._SUPPLIER_LOOKUP_CHUNK`` and exists for the same reason:
# every driver bounds the parameters a single statement may take, and this is
# a list that grows with the customer base rather than with the work.
_TENANT_LOOKUP_CHUNK = 500


def _chunked(items: Sequence[int]) -> Iterator[Sequence[int]]:
    """``items`` in slices no statement's parameter list will choke on."""
    for start in range(0, len(items), _TENANT_LOOKUP_CHUNK):
        yield items[start : start + _TENANT_LOOKUP_CHUNK]


@dataclass(frozen=True)
class AlertEmailResult:
    """What one run of the digest sender did. Returned so the Celery task has
    a result worth recording and the numbers can be asserted on, the same
    reasoning as :class:`app.services.alerting.SweepResult`.
    """

    businesses: int = 0
    emails_sent: int = 0
    alerts_sent: int = 0
    alerts_failed: int = 0
    skipped_no_recipient: int = 0

    def as_dict(self) -> dict:
        return {
            "businesses": self.businesses,
            "emails_sent": self.emails_sent,
            "alerts_sent": self.alerts_sent,
            "alerts_failed": self.alerts_failed,
            "skipped_no_recipient": self.skipped_no_recipient,
        }


def _outstanding_by_business(
    db: Session, business_ids: Sequence[int]
) -> dict[int, list[Row]]:
    """Every sendable alert for ``business_ids``, grouped, in send order.

    Selected as columns rather than as ``Alert`` instances, and that is the
    whole reason this can be hoisted out of the loop at all. The loop commits
    per business; a commit expires every ORM instance in the session, so a
    prefetch of mapped objects would be re-read attribute by attribute after
    the first tenant — one statement per *alert* rather than per tenant, which
    is worse than the read it replaced. A ``Row`` belongs to no session and
    survives the commit intact, the same reasoning as the recipients above.

    Note what is *not* hoisted: the send and the write stay inside the loop,
    one tenant at a time, because those are what the per-business commit
    isolates. Reading early costs that nothing — a failure here is a failure
    of the whole run either way, exactly as the two statements before it
    already are.
    """
    by_business: dict[int, list[Row]] = {}
    for chunk in _chunked(business_ids):
        rows = db.execute(
            select(Alert.id, Alert.business_id, Alert.title, Alert.message, Alert.due_date)
            .where(
                Alert.business_id.in_(chunk),
                Alert.status.in_(_SENDABLE_STATUSES),
                Alert.deleted_at.is_(None),
            )
            # ``business_id`` leads only to make the grouping below a single
            # pass; within a tenant the order is the one the digest has always
            # been written in.
            .order_by(Alert.business_id, Alert.due_date, Alert.id)
        ).all()
        for row in rows:
            by_business.setdefault(row.business_id, []).append(row)
    return by_business


def _digest(alerts: list[Row]) -> tuple[str, str]:
    """The subject and body for one business's outstanding alerts."""
    subject = (
        "1 GST alert needs your attention"
        if len(alerts) == 1
        else f"{len(alerts)} GST alerts need your attention"
    )
    lines = ["DoAide GST has the following open items:", ""]
    for alert in alerts:
        due = f" (due {alert.due_date.isoformat()})" if alert.due_date else ""
        lines.append(f"- {alert.title}{due}")
        lines.append(f"  {alert.message}")
        lines.append("")
    lines.append("Sign in to DoAide GST to review or dismiss these.")
    return subject, "\n".join(lines)


def _recipients(business: Business, linked: Collection[str] = ()) -> list[str]:
    """Every active user's email, and every linked login that can file, in a
    stable order.

    Not just the owner: an accountant added to the business is exactly who
    should hear about a deadline they may be the one filing. An accountant
    reaches a client's business through a link (``/businesses/mine/link``), a
    membership rather than a user of that business, so ``business.users``
    alone never told them. See :func:`_linked_recipients`.
    """
    own = {u.email for u in business.users if u.is_active and u.email}
    return sorted(own | set(linked))


# The membership roles that can act on a deadline. A viewer cannot file.
_LINKED_ROLES_TOLD = (MembershipRole.OWNER, MembershipRole.ACCOUNTANT)


def _linked_recipients(db: Session, business_ids: Collection[int]) -> dict[int, set[str]]:
    """``{business_id: emails}`` of the live owner and accountant links to them.

    One statement for a whole chunk, like the users beside it, so the digest
    reads no more per tenant than it did.
    """
    rows = db.execute(
        select(BusinessMembership.business_id, User.email)
        .join(User, User.id == BusinessMembership.user_id)
        .where(
            BusinessMembership.business_id.in_(business_ids),
            BusinessMembership.deleted_at.is_(None),
            BusinessMembership.role.in_(_LINKED_ROLES_TOLD),
            User.is_active.is_(True),
            User.email.is_not(None),
        )
    ).all()
    linked: dict[int, set[str]] = {}
    for business_id, email in rows:
        linked.setdefault(business_id, set()).add(email)
    return linked


def _send_to_all(recipients: list[str], subject: str, body: str, *, business_id: int) -> bool:
    """Try every recipient; a business counts as reached if any one of them got it."""
    reached = False
    for address in recipients:
        try:
            send_email(to=address, subject=subject, body=body)
            reached = True
        except EmailSendError:
            logger.warning(
                "Alert email failed for recipient",
                exc_info=True,
                extra={"business_id": business_id},
            )
    return reached


def send_pending_alerts(db: Session, *, now: datetime | None = None) -> AlertEmailResult:
    """Email each business one digest of its undelivered alerts.

    A no-op, safely, when email is not configured — the same trade the rest of
    this product makes for OpenRouter: a missing integration degrades the
    feature it powers rather than failing the process that would otherwise run
    fine without it.
    """
    if not settings.alerts_email_enabled or not settings.smtp_host:
        return AlertEmailResult()

    with _sole_run(db) as alone:
        if not alone:
            logger.info("Alert email digest already running elsewhere; skipping")
            return AlertEmailResult()
        return _send_pending_alerts(db, now=now or datetime.now(UTC))


# Arbitrary, and the one-argument form, so it cannot meet the two-key
# per-business locks taken elsewhere in this database.
_DIGEST_LOCK_KEY = 7_365_401


@contextmanager
def _sole_run(db: Session) -> Iterator[bool]:
    """Yield whether this is the only digest run in progress.

    The task is acks_late, so a redelivery, a retry or a run started by hand
    can overlap one already sending. Both read the same pending alerts before
    either stamps them, and each emailed the same digest. A per-tenant row lock
    would close that too, but it is a read per tenant, which this module
    deliberately has none of.

    A session-level advisory lock on a connection of its own: the run commits
    per business, and the session's connection can go back to the pool at each
    commit, taking a lock held on it along. ``try`` rather than wait, because
    the overlapping run is doing this run's work already. Postgres releases it
    if the process dies. SQLite has one writer and no advisory locks.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect() as conn:
        acquired = bool(conn.scalar(select(func.pg_try_advisory_lock(_DIGEST_LOCK_KEY))))
        try:
            yield acquired
        finally:
            if acquired:
                conn.scalar(select(func.pg_advisory_unlock(_DIGEST_LOCK_KEY)))


def _send_pending_alerts(db: Session, *, now: datetime) -> AlertEmailResult:

    # Which tenants have something to send, answered out of
    # ``ix_alerts_status_business`` alone — see
    # ``tests/test_sweep_indexes.py``, which plans this statement and fails if
    # it stops being an index-only search. Driving the other way round, from
    # ``businesses`` joined to ``alerts``, reads better but plans worse: the
    # planner scans every tenant, including the overwhelming majority with no
    # alert pending, to probe for the few that have one.
    business_ids = db.scalars(
        select(Alert.business_id)
        .where(Alert.status.in_(_SENDABLE_STATUSES), Alert.deleted_at.is_(None))
        .distinct()
        .order_by(Alert.business_id)
    ).all()

    # Then those tenants and their recipients, in a bounded number of
    # statements rather than two per tenant. This is the one place in the
    # product that deliberately loops over every business at once, so a
    # per-tenant read here is multiplied by the customer list rather than by
    # anything about the work. It used to be exactly that: ``db.get`` per id,
    # then ``business.users`` inside ``_recipients``, which is a lazy
    # relationship and so a second statement again, and then the alerts
    # themselves — 3N round trips before a single email was composed. The
    # whole read side is three statements per chunk now, and the loop below
    # issues none.
    #
    # Chunked for the reason ``reconciliation._suppliers_by_gstin`` is: every
    # driver bounds the parameters one statement may carry, and the whole
    # point of this list is that it grows with the customer base.
    #
    # ``selectinload`` rather than a join for the users: a business has many,
    # and joining would multiply each business row by its user count and leave
    # this loop de-duplicating. One extra statement per chunk, covering all of
    # that chunk's users together, is the cheaper shape.
    #
    # Read straight out to plain data, because the loop below commits. A
    # commit expires every instance in the session, so a ``business.users``
    # read after the first tenant's commit would go back to the database and
    # put the per-tenant round trip right back — loading it eagerly only helps
    # for as long as nothing expires it.
    digest_targets: list[tuple[int, list[str]]] = []
    for chunk in _chunked(business_ids):
        businesses = db.scalars(
            select(Business)
            .where(
                Business.id.in_(chunk),
                Business.deleted_at.is_(None),
                Business.is_active.is_(True),
            )
            .options(selectinload(Business.users))
            .order_by(Business.id)
        ).all()
        linked = _linked_recipients(db, chunk)
        digest_targets.extend((b.id, _recipients(b, linked.get(b.id, ()))) for b in businesses)

    # And the alerts themselves, for every tenant at once. Read after the
    # businesses rather than with them so that a tenant deactivated between the
    # two is not paid for here — and read at all only for the tenants that
    # survived that filter.
    outstanding = _outstanding_by_business(db, [bid for bid, _ in digest_targets])

    t_biz = t_sent = t_alerts_sent = t_alerts_failed = t_skipped = 0
    for business_id, recipients in digest_targets:
        alerts = outstanding.get(business_id, [])
        # Still reachable, and still a ``continue`` rather than a ``return``.
        # The id scan and this read are separate statements, and the sweep, the
        # alerts API and a tenant deletion all write these rows from other
        # connections — so a business named by the scan can have nothing left
        # by the time this asks. See
        # ``TestAlertsThatVanishBetweenTheTwoQueries``.
        if not alerts:
            continue

        if not recipients:
            t_skipped += len(alerts)
            continue

        subject, body = _digest(alerts)

        # The send itself is inside the try, not just the commit after it.
        # ``_send_to_all`` only ever catches :class:`EmailSendError` — the type
        # :func:`send_email` promises to raise for a relay it can reach and
        # fails against. A misconfigured relay does not keep to that contract:
        # ``smtplib.SMTP.login`` with a username set and no password raises
        # ``AttributeError``, not ``SMTPException``, and nothing upstream of
        # here is prepared to see one. Left outside the try, that one bad
        # tenant's config would propagate out of this function entirely and
        # take every business after it in ``business_ids`` down with it — the
        # exact failure the per-business commit below exists to rule out, and
        # the one the module docstring promises will not happen.
        try:
            reached = _send_to_all(recipients, subject, body, business_id=business_id)
            # Stamped by id in one statement rather than attribute by attribute
            # on mapped instances, because there are no mapped instances to
            # stamp any more — see ``_outstanding_by_business``. ``sent_at`` is
            # left alone on a failure, as it always was: the row is a delivery
            # that has not happened, and dating it would make it one that did.
            stamp = (
                {"channel": _CHANNEL, "sent_at": now, "status": AlertStatus.SENT}
                if reached
                else {"channel": _CHANNEL, "status": AlertStatus.FAILED}
            )
            for ids in _chunked([alert.id for alert in alerts]):
                db.execute(
                    update(Alert)
                    .where(
                        Alert.id.in_(ids),
                        # The sweep or a user action may have changed the status
                        # between the prefetch and this write.  Without this
                        # guard, a RESOLVED or DISMISSED alert would be
                        # overwritten with SENT.
                        Alert.status.in_(_SENDABLE_STATUSES),
                    )
                    .values(**stamp)
                    # Nothing in this session is mapped to these rows, so there
                    # is no in-memory state to reconcile and the extra SELECT
                    # the default strategy would issue buys nothing.
                    .execution_options(synchronize_session=False)
                )
            db.commit()
        except Exception:  # noqa: BLE001 - one tenant must not end the run
            db.rollback()
            logger.exception(
                "Could not send/record alert delivery",
                extra={"business_id": business_id, "alert_count": len(alerts)},
            )
            t_biz += 1
            t_alerts_failed += len(alerts)
            continue

        t_biz += 1
        if reached:
            t_sent += 1
            t_alerts_sent += len(alerts)
        else:
            t_alerts_failed += len(alerts)

    total = AlertEmailResult(
        businesses=t_biz,
        emails_sent=t_sent,
        alerts_sent=t_alerts_sent,
        alerts_failed=t_alerts_failed,
        skipped_no_recipient=t_skipped,
    )
    logger.info("Alert email digest completed", extra=total.as_dict())
    return total
