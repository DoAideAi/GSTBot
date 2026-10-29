"""Raising the deadline alerts the alerts table was built for.

``app/models/alert.py`` has described filing-deadline alerts, with delivery
state on the row, since the first migration — and until now nothing wrote one.
The dashboard has been counting them the whole time, which means it has been
reporting zero to every business on every load: not "you are up to date" but
"nothing here has an opinion", rendered identically.

This is the sweep that gives it an opinion. It runs once a day, reads where each
return stands, and keeps one alert per period and return type in step with it.

**Why a sweep rather than an event.** A deadline is not something that happens;
it is something that fails to happen. There is no request to hang the alert off
— the business simply does not file — so the only thing that can notice is a
clock. That is also why this is idempotent rather than incremental: the day's
truth is recomputed from the returns table each morning, so a sweep that was
skipped, ran twice, or ran on a box whose clock had drifted converges the next
morning regardless.

**What decides whether someone is told.** Three rules, all of them about not
becoming noise, because the product only gets one chance at this — a business
that is nagged about returns it has already filed turns notifications off once,
permanently, and is then not told about the one that matters.

1. *Nothing before the business existed.* A period that closed before signup is
   one this application holds no invoices for and cannot know the filing status
   of. Asserting that it is late is a guess, and six confident, wrong alerts on
   day one is the fastest way to lose the channel.
2. *Nothing until the deadline is near.* An alert three weeks out is not news;
   it is furniture. The first one lands :data:`LEAD_DAYS` before the due date.
3. *A dismissal is respected.* Closing an alert means "I know". The sweep will
   not raise a second copy tomorrow. It reopens one only when the severity
   genuinely changes — the deadline moving from approaching to missed is new
   information, and it can happen at most twice per return.

**What this does not do.** It does not send anything. The alert row is created
and the business sees it in the product; nothing here reaches email, SMS or
WhatsApp, and ``channel`` and ``sent_at`` stay null to say so. The feature doc
promises those channels and no infrastructure for any of them exists yet, so
what ships is the half that is real: the alert is raised, correctly and on time,
and whoever adds a sender has a durable row to send and to mark.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.models.alert import (
    OPEN_STATUSES,
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.business import Business
from app.models.gstr_return import ReturnType
from app.services import filing as filing_service
from app.services import gst_calendar, itc_deadline

logger = logging.getLogger(__name__)

# How many completed periods each sweep looks back over. Six matches the filing
# status endpoint, so the alerts and the screen they link to cover the same
# ground. Further back than that, an unfiled return is a standing liability
# rather than a reminder, and its alert has already been raised — falling out of
# the window stops the wording being refreshed, not the alert existing.
WINDOW_PERIODS = 6

# Days before the due date at which the first alert appears. Seven puts GSTR-1
# on the 4th and GSTR-3B on the 13th, which is a working week either side — long
# enough to collect what is missing, short enough that the alert is still about
# this month.
LEAD_DAYS = 7

# ...and at which it stops being merely informational.
URGENT_DAYS = 3

# What a business calls each return. The enum values are storage.
RETURN_LABEL = {ReturnType.GSTR1: "GSTR-1", ReturnType.GSTR3B: "GSTR-3B"}



@dataclass(frozen=True)
class SweepResult:
    """What one run of the sweep changed.

    Returned rather than logged alone so the Celery task has a result worth
    recording, and so the numbers can be asserted on.
    """

    businesses: int = 0
    raised: int = 0
    reopened: int = 0
    resolved: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "businesses": self.businesses,
            "raised": self.raised,
            "reopened": self.reopened,
            "resolved": self.resolved,
            "failed": self.failed,
        }


def _severity(standing: filing_service.ReturnStanding) -> AlertSeverity:
    """How loud this deadline should be.

    Only ever escalates as the date approaches, which is what makes "the
    severity changed" a safe trigger for reopening a dismissed alert: it can
    fire at most twice for one return, and never once the return is late.
    """
    if standing.overdue:
        return AlertSeverity.CRITICAL
    if standing.days_until_due <= URGENT_DAYS:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def wording(standing: filing_service.ReturnStanding) -> tuple[str, str]:
    """The title and body for one outstanding return.

    Deliberately vague about the penalty. Interest and the daily late fee are
    real and are the reason this alert exists, but their rates are set by
    notification and have been changed more than once; a figure hard-coded here
    would eventually be quoted, confidently and wrongly, to someone deciding
    what to do. What the product can state precisely is the date, and that the
    return has not been recorded as filed.
    """
    label = RETURN_LABEL[standing.return_type]
    due = standing.due_date.isoformat()
    days = standing.days_until_due

    if standing.overdue:
        title = f"{label} for {standing.period} is overdue"
        body = (
            f"{label} for {standing.period} was due on {due} and has not been "
            f"recorded as filed — {_plural(-days, 'day')} ago. Interest and a "
            f"late fee accrue for as long as it stays unfiled."
        )
    elif days == 0:
        title = f"{label} for {standing.period} is due today"
        body = (
            f"{label} for {standing.period} is due today, {due}, and has not "
            f"been recorded as filed."
        )
    else:
        title = f"{label} for {standing.period} is due in {_plural(days, 'day')}"
        body = (
            f"{label} for {standing.period} is due on {due} and has not been "
            f"recorded as filed."
        )

    return title, (
        f"{body} If it has already been filed on the portal, record it here and "
        f"this alert will close."
    )


def _first_period(business: Business | Row) -> str | None:
    """The earliest period this business can be told anything about.

    ``None`` when the row has not been flushed and has no ``created_at`` yet,
    which only happens in a test that built one by hand; there is no signup date
    to be cautious about, so nothing is excluded.
    """
    created = business.created_at
    return gst_calendar.period_of(gst_calendar.ist_date(created)) if created else None


def _existing(
    db: Session, business_id: int, periods: list[str]
) -> dict[tuple[str, ReturnType], Alert]:
    """Filing-deadline alerts already raised over *periods*, keyed by what they cover.

    Closed alerts are included on purpose, and that is the whole point of
    looking them up rather than inserting freely: a dismissed alert is the
    business having said "I know", and a sweep that only saw live ones would
    raise an identical copy every morning.

    Keyed off ``context["return_type"]`` because the period is a column and the
    return type is not. Matching in Python rather than in the query keeps this
    off JSON operators, which differ between the Postgres this deploys on and
    the SQLite the suite runs — the kind of split where a query works in tests
    and silently matches nothing in production.
    """
    if not periods:
        return {}

    rows = db.scalars(
        select(Alert)
        .where(
            Alert.business_id == business_id,
            Alert.alert_type == AlertType.FILING_DEADLINE,
            Alert.deleted_at.is_(None),
            Alert.period.in_(periods),
        )
        .order_by(Alert.id)
    ).all()

    found: dict[tuple[str, ReturnType], Alert] = {}
    for row in rows:
        stored = (row.context or {}).get("return_type")
        try:
            return_type = ReturnType(stored)
        except ValueError:
            # An alert covering a return type this build no longer knows about.
            # Leaving it alone is better than raising a duplicate beside it.
            continue
        # Narrowing, not a filter: the key this builds is typed on ``str`` and
        # ``Alert.period`` is nullable. A row that fails it cannot arrive —
        # ``period IN (...)`` is never true of NULL — so there is no case here
        # to test and no coverage to be had.
        if row.period is not None:  # pragma: no branch
            found[(row.period, return_type)] = row
    return found


def sweep_business(
    db: Session, business: Business | Row, *, today: date
) -> SweepResult:
    """Bring one tenant's deadline alerts into line with what they have filed.

    Adds nothing to the session that a caller does not commit, so a tenant whose
    data trips something can be rolled back on its own.
    """
    first = _first_period(business)
    periods = [
        period
        for period in gst_calendar.completed_periods(today, WINDOW_PERIODS)
        if first is None or period >= first
    ]
    # The s.16(4) pass is not scoped to that six-period window and runs whether
    # or not it is empty. Its deadline is up to nineteen months behind the
    # invoice, so the year it is about has long since dropped out of the
    # filing sweep's window — scoping it the same way would mean the alert
    # could only ever fire for credit that was not yet at risk.
    itc = sweep_itc_deadlines(db, business, today=today)

    if not periods:
        return SweepResult(
            businesses=1,
            raised=itc.raised,
            reopened=itc.reopened,
            resolved=itc.resolved,
        )

    standings = filing_service.standings(
        db, business.id, periods=periods, as_of=today
    )
    existing = _existing(db, business.id, periods)

    raised = reopened = resolved = 0

    for standing in standings:
        alert = existing.get((standing.period, standing.return_type))

        if standing.filed:
            # Filing is the only thing that closes this on its own. Recorded
            # late still closes it: the alert asks for a filing, not a punctual
            # one, and leaving it open would be nagging about something done.
            if alert is not None and alert.status in OPEN_STATUSES:
                alert.status = AlertStatus.RESOLVED
                resolved += 1
            continue

        if standing.days_until_due > LEAD_DAYS:
            continue

        severity = _severity(standing)
        title, message = wording(standing)

        if alert is None:
            db.add(
                Alert(
                    business_id=business.id,
                    alert_type=AlertType.FILING_DEADLINE,
                    severity=severity,
                    status=AlertStatus.PENDING,
                    title=title,
                    message=message,
                    period=standing.period,
                    due_date=standing.due_date,
                    context={"return_type": standing.return_type.value},
                )
            )
            raised += 1
            continue

        # A return that was recorded filed and then had that record removed. The
        # obligation is back, so the alert is too.
        undone = alert.status is AlertStatus.RESOLVED
        escalated = alert.severity is not severity

        if alert.status in OPEN_STATUSES or undone or escalated:
            # "due in 3 days" is wrong tomorrow, so the wording is rewritten
            # rather than left as whatever the day it was raised said.
            alert.title = title
            alert.message = message
            alert.severity = severity
            alert.due_date = standing.due_date

        if undone or (escalated and alert.status not in OPEN_STATUSES):
            alert.status = AlertStatus.PENDING
            reopened += 1
        elif escalated and alert.status in (AlertStatus.READ, AlertStatus.SENT):
            # The severity changed since the user last saw (READ) or was
            # emailed (SENT) this alert.  Back to pending so the new severity
            # reaches the email sender.
            alert.status = AlertStatus.PENDING

    return SweepResult(
        businesses=1,
        raised=raised + itc.raised,
        reopened=reopened + itc.reopened,
        resolved=resolved + itc.resolved,
    )


def _money(amount) -> str:
    """A rupee figure as a business would read it, to the rupee.

    Paise are dropped on purpose. This number exists to convey scale — "you are
    about to lose ₹1,42,318" — and two decimal places on a figure that large
    reads as a false claim to exactness about a total assembled from invoices
    the product parsed itself.
    """
    return f"₹{amount.quantize(Decimal('1')):,}"


def itc_wording(row: itc_deadline.LapsingCredit) -> tuple[str, str]:
    """The title and body for one financial year's lapsing credit.

    States the date and the amount and stops. Unlike a missed filing, there is
    no discretion left to describe once the day passes — the credit is not
    recoverable by acting faster, so wording that implies otherwise would be
    the cruellest kind of wrong.
    """
    year = row.financial_year
    amount = _money(row.total)
    invoices = _plural(row.invoice_count, "purchase invoice")
    deadline = row.deadline.isoformat()

    if row.expired:
        return (
            f"Input credit for {year} has lapsed",
            f"{amount} of input tax credit on {invoices} for {year} was never "
            f"taken into a GSTR-3B, and the deadline under section 16(4) passed "
            f"on {deadline}. This credit can no longer be claimed. If these "
            f"returns were in fact filed on the portal, record them here — the "
            f"credit is only lost if they genuinely were not.",
        )

    days = row.days_remaining
    when = "today" if days == 0 else f"in {_plural(days, 'day')}"
    return (
        f"Input credit for {year} lapses {when}",
        f"{amount} of input tax credit on {invoices} for {year} has not been "
        f"taken into a GSTR-3B. Under section 16(4) it must be claimed by "
        f"{deadline}, after which it is lost permanently — there is no late fee "
        f"for this and no way to claim it afterwards. Filing the outstanding "
        f"GSTR-3B for {', '.join(row.periods) or 'the affected periods'} is what "
        f"secures it. If your annual return for {year} is filed before that "
        f"date, the deadline is that date instead.",
    )


def _itc_severity(row: itc_deadline.LapsingCredit) -> AlertSeverity:
    if row.expired:
        return AlertSeverity.CRITICAL
    if row.days_remaining <= itc_deadline.URGENT_DAYS:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _existing_itc(db: Session, business_id: int) -> dict[str, Alert]:
    """ITC-lapse alerts already raised, keyed by financial year.

    Unfiltered by period because these alerts carry none: a financial year is
    not a ``YYYY-MM`` and putting one in that column would break the listing
    endpoint's period filter, which promises a filing period. The year lives in
    ``context`` and the whole set is loaded — there is at most one row per
    financial year per tenant, so this is a handful of rows however long the
    business has been trading.
    """
    rows = db.scalars(
        select(Alert)
        .where(
            Alert.business_id == business_id,
            Alert.alert_type == AlertType.ITC_AT_RISK,
            Alert.deleted_at.is_(None),
        )
        .order_by(Alert.id)
    ).all()

    found: dict[str, Alert] = {}
    for row in rows:
        year = (row.context or {}).get("financial_year")
        if isinstance(year, str):
            found[year] = row
    return found


def sweep_itc_deadlines(
    db: Session, business: Business | Row, *, today: date
) -> SweepResult:
    """Keep one tenant's s.16(4) alerts in step with what is still unclaimed.

    Same three rules as the filing sweep — nothing before signup, nothing
    outside the lead window, a dismissal is respected — with one difference
    that matters: severity here escalates to CRITICAL on the day the credit
    lapses, and that escalation reopens a dismissed alert. Dismissing "lapses
    in 60 days" is a reasonable thing to do in September; it is not consent to
    never hear that it happened.

    Adds nothing the caller does not commit, so it shares the filing sweep's
    per-tenant rollback.
    """
    at_risk = itc_deadline.at_risk(
        db, business.id, as_of=today, since_period=_first_period(business)
    )
    existing = _existing_itc(db, business.id)

    raised = reopened = resolved = 0
    live = {row.financial_year for row in at_risk}

    for row in at_risk:
        severity = _itc_severity(row)
        title, message = itc_wording(row)
        alert = existing.get(row.financial_year)

        if alert is None:
            db.add(
                Alert(
                    business_id=business.id,
                    alert_type=AlertType.ITC_AT_RISK,
                    severity=severity,
                    status=AlertStatus.PENDING,
                    title=title,
                    message=message,
                    due_date=row.deadline,
                    context={
                        "financial_year": row.financial_year,
                        "amount": str(row.total),
                        "invoice_count": row.invoice_count,
                        "periods": list(row.periods),
                    },
                )
            )
            raised += 1
            continue

        undone = alert.status is AlertStatus.RESOLVED
        escalated = alert.severity is not severity

        if alert.status in OPEN_STATUSES or undone or escalated:
            # The amount moves as invoices are added or periods are filed, so
            # the body is rewritten rather than left saying what was true the
            # morning it was raised.
            alert.title = title
            alert.message = message
            alert.severity = severity
            alert.due_date = row.deadline
            alert.context = {
                "financial_year": row.financial_year,
                "amount": str(row.total),
                "invoice_count": row.invoice_count,
                "periods": list(row.periods),
            }

        if undone or (escalated and alert.status not in OPEN_STATUSES):
            alert.status = AlertStatus.PENDING
            reopened += 1
        elif escalated and alert.status in (AlertStatus.READ, AlertStatus.SENT):
            alert.status = AlertStatus.PENDING

    # A year that has dropped off the list has had its returns recorded — every
    # invoice that was unclaimed is now in a filed GSTR-3B. Whether that
    # happened before the deadline or after it, there is nothing further to
    # ask for, so the alert closes.
    for year, alert in existing.items():
        if year not in live and alert.status in OPEN_STATUSES:
            alert.status = AlertStatus.RESOLVED
            resolved += 1

    return SweepResult(raised=raised, reopened=reopened, resolved=resolved)


# Session-level advisory lock for the sweep, beside the digest's 7_365_401 in
# alert_delivery. Single-key space; the per-tenant locks elsewhere use the
# two-integer space and cannot collide with it.
_SWEEP_LOCK_KEY = 7_365_402


@contextmanager
def _sole_sweep(db: Session) -> Iterator[bool]:
    """Yield whether this is the only deadline sweep in progress.

    "Ran twice converges" holds for runs one after the other. Two at once — a
    redelivered acks_late task, a second beat, a run by hand — both find no
    alert for a period and both insert one; alerts have no unique key to stop
    it. The pair then outlives the filing: the next sweep keys what exists by
    (period, return type), keeps one of the two, resolves that one when the
    return is filed, and the other stays pending and is emailed every morning.

    The same lock the digest takes, for the same reasons: on a connection of
    its own, because the sweep commits per business; ``try`` rather than wait,
    because the overlapping run is already doing this one's work.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect() as conn:
        acquired = bool(conn.scalar(select(func.pg_try_advisory_lock(_SWEEP_LOCK_KEY))))
        try:
            yield acquired
        finally:
            if acquired:
                conn.scalar(select(func.pg_advisory_unlock(_SWEEP_LOCK_KEY)))


def sweep_filing_deadlines(db: Session, *, today: date | None = None) -> SweepResult:
    """Run the deadline sweep, unless another one is already running."""
    with _sole_sweep(db) as sole:
        if not sole:
            logger.info("Filing deadline sweep skipped: another sweep is running")
            return SweepResult()
        return _sweep_filing_deadlines(db, today=today)


def _sweep_filing_deadlines(db: Session, *, today: date | None = None) -> SweepResult:
    """Raise, refresh and close filing-deadline alerts for every active tenant.

    Committed per business rather than once at the end. A nightly job that dies
    on the third tenant and never reaches the four-hundredth is the failure mode
    worth designing against, so one tenant's bad data costs that tenant's alerts
    for a day and nothing else — and because the sweep is idempotent, the next
    morning tries again from the same starting point.

    One pass loads every active business, then costs each one a fixed seven
    statements: two returns' standings and existing alerts, the s.16(4) pass's
    purchases, and the alerts it writes (``TestTheSweepPaysAFixedCostPerTenant``
    pins it). That is fine at the scale this runs at and is not fine at every
    scale; the shape to reach for when it stops being fine is batching by
    period across tenants, not a longer interval.

    The businesses are loaded as plain (id, created_at) rows, which is all the
    sweep reads. As ORM objects, the commit after each tenant expired the rest,
    and each was read from the database a second time on first touch.
    """
    today = today or gst_calendar.today_ist()

    businesses = db.execute(
        select(Business.id, Business.created_at)
        .where(Business.deleted_at.is_(None), Business.is_active.is_(True))
        .order_by(Business.id)
    ).all()

    t_businesses = t_raised = t_reopened = t_resolved = t_failed = 0
    for business in businesses:
        try:
            one = sweep_business(db, business, today=today)
            db.commit()
        except Exception:  # noqa: BLE001 - one tenant must not end the sweep
            db.rollback()
            logger.exception(
                "Filing deadline sweep failed for business %s", business.id,
                extra={"business_id": business.id},
            )
            t_businesses += 1
            t_failed += 1
            continue

        t_businesses += one.businesses
        t_raised += one.raised
        t_reopened += one.reopened
        t_resolved += one.resolved

    total = SweepResult(
        businesses=t_businesses,
        raised=t_raised,
        reopened=t_reopened,
        resolved=t_resolved,
        failed=t_failed,
    )

    logger.info(
        "Filing deadline sweep completed",
        extra={
            "date": today.isoformat(),
            "businesses": total.businesses,
            "raised": total.raised,
            "reopened": total.reopened,
            "resolved": total.resolved,
            "failed": total.failed,
        },
    )
    return total
