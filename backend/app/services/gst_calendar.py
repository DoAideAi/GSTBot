"""When a return for a period is due.

A monthly return's due date is arithmetic on the period, not a lookup: every
one of them falls on a fixed day of the *following* month, so the whole rule is
a day number plus a December rollover.

That is short enough that it had already been written twice — once in the
dashboard for GSTR-3B and once in supplier scoring for GSTR-1, each with its
own copy of the rollover — and the alerting needs both. Three copies of a rule
the government does move (the 3B date has been staggered by turnover before,
and quarterly filers under QRMP follow a different one entirely) is three
places to miss when it changes next, so it lives here once.

Only the returns *this business files* have a due date. A GSTR-2B is generated
by the portal rather than submitted to it, so asking when one is due is a
question about a return that is never late; :func:`due_date` refuses it rather
than inventing a day.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from app.models.gstr_return import ReturnType

# The only shape a filing period may take: ``YYYY-MM`` naming a month that
# exists *and* that a GST return could cover.
#
# ``\d{4}-\d{2}`` is the obvious pattern and it is not a period validator — it
# admits ``2026-00`` and ``2026-13``, and every route that took one handed it
# straight to arithmetic that assumes a real month. ``next_period("2026-13")``
# is ``2026-14``, which ``date()`` refuses, so a due date computed from it was
# a 500 rather than the 422 a malformed query string has earned. The ones that
# did not raise were worse: ``2026-13`` built a GSTR-1 stamped ``fp=132026``
# and ``2026-00`` quietly aliased onto January, both of them documents about a
# month that does not exist.
#
# Checking the month alone leaves the same defect at the other end of the
# field. ``\d{4}`` reaches both edges of ``date()``'s 1..9999: the dashboard
# asks for the *following* month's due date, so ``9999-12`` raised
# ``year must be in 1..9999, not 10000`` and ``0000-01`` raised on the year
# before — a 500 on the product's front page from a query string. And the
# routes that survived it are the worse half again, because ``9999-12`` built
# and exported a GSTR-1 stamped ``fp=129999`` and the validation screen called
# a return for the year 9999 ``ok: true``.
#
# So the bound is the same one :func:`is_filable_invoice_date` puts on an
# invoice date, for the same reason: a period is a month a return is filed
# for, and there is no return for a month before GST existed. July 2017 is
# where GST commenced — see :data:`GST_COMMENCEMENT` — and 2099 is a century of
# headroom, chosen because it keeps every derived date (a due date is next
# month, Rule 43 looks back sixty) inside the range ``date()`` will construct.
# Anything outside it is a typo or a probe, and both want the same 422.
#
# Anchored, so it validates the same whether a caller matches or searches with
# it. Exported as the single definition every route, schema and importer spells
# the period with.
#
# ``[0-9]`` and never ``\d``: pydantic's regex engine, like Python's, reads
# ``\d`` as any Unicode digit, so ``202٦-04`` passed, was recorded as a filed
# GSTR-3B under that string, and matched no period the app ever asks about.
PERIOD_PATTERN = r"^(?:2017-(?:0[7-9]|1[0-2])|20(?:1[89]|[2-9][0-9])-(?:0[1-9]|1[0-2]))$"

_PERIOD_RE = re.compile(PERIOD_PATTERN)

# The two ends of that span, spelled out. A caller refusing a period should be
# able to say what the range is without a reader having to run the regex in
# their head, and the suite pins these against the pattern so the prose in an
# error message cannot drift away from what is actually enforced.
FIRST_PERIOD = "2017-07"
LAST_PERIOD = "2099-12"

# Every date in this module is an Indian one. A due date falls at the end of
# the 20th *in India*, so a server running on UTC is already a day behind by
# 18:30 local — which would have the alerting call a return on time for another
# five and a half hours after the penalty started running.
#
# A fixed offset rather than ``ZoneInfo("Asia/Kolkata")``: India has not
# observed daylight saving since 1945 and IST has been UTC+05:30 throughout, so
# there is no rule to look up, and this needs no tzdata on the host.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

# The day GST commenced. Nothing before it can be a GST invoice: there was no
# GSTIN to put on one and no return to file it in. Useful as the far end of
# "is this a date an invoice could carry" — a misread year is otherwise
# indistinguishable from a real one, and the period it derives is a month no
# return will ever cover.
GST_COMMENCEMENT = date(2017, 7, 1)

# GSTR-1 — outward supplies — is due on the 11th of the month after the period.
GSTR1_DUE_DAY = 11

# GSTR-3B — the summary and the payment — is due on the 20th. This is the one
# that carries interest and a late fee, which is why it is the date the
# dashboard leads with.
GSTR3B_DUE_DAY = 20


def today_ist() -> date:
    """The current date in India — the only date a GST deadline is measured in."""
    return datetime.now(IST).date()


def ist_date(moment: datetime) -> date:
    """The Indian calendar date a stored instant falls on.

    Reading ``.date()`` off a timestamp straight out of the database is wrong
    on the backend that ships and right on the one the suite runs, which is the
    worst combination available. Midnight IST is 18:30 *the previous day* in
    UTC, so a filing recorded on the 15th comes back from Postgres — which
    stores ``timestamptz`` normalised to UTC — as the 14th, and every recorded
    filing is reported a day early. SQLite has no zone at all: SQLAlchemy
    formats the wall clock and drops the offset, so the same call returns the
    15th and the test suite sees nothing wrong.

    A naive value is therefore read as the IST wall time it was written as, and
    an aware one is converted.
    """
    return moment.date() if moment.tzinfo is None else moment.astimezone(IST).date()


def is_period(value: object) -> bool:
    """Whether *value* is a ``YYYY-MM`` period naming a month that exists."""
    return isinstance(value, str) and _PERIOD_RE.match(value) is not None


def is_filable_invoice_date(value: date, *, today: date | None = None) -> bool:
    """Whether *value* is a day an invoice could be dated and still be filed.

    Between the day GST commenced and today, in India. Both ends are typos
    rather than edge cases — a slipped year on a keyboard, a misread digit out
    of OCR — and both have the same consequence, which is why they are one
    question: the filing period is derived from this date, so a date outside
    the range puts the invoice in a month no return will ever cover. It leaves
    the register, the dashboard, the reconciliation and the GSTR-1 in one step,
    and nothing downstream is left to notice, because every one of those is
    scoped to a period and this invoice is no longer in any of them.
    """
    return GST_COMMENCEMENT <= value <= (today or today_ist())


def period_of(moment: date) -> str:
    """The ``YYYY-MM`` period *moment* falls in."""
    return f"{moment.year:04d}-{moment.month:02d}"


def next_period(period: str) -> str:
    """The ``YYYY-MM`` period after *period*."""
    year, month = (int(part) for part in period.split("-"))
    return f"{year + 1:04d}-01" if month == 12 else f"{year:04d}-{month + 1:02d}"


def previous_period(period: str) -> str:
    """The ``YYYY-MM`` period before *period*."""
    year, month = (int(part) for part in period.split("-"))
    return f"{year - 1:04d}-12" if month == 1 else f"{year:04d}-{month - 1:02d}"


def months_before(period: str, count: int) -> str:
    """The ``YYYY-MM`` period *count* months before *period*.

    Repeated :func:`previous_period` would do, and does not scale: Rule 43
    spreads a capital good's credit over sixty months, so the window it needs
    is five years wide. Counting in months-since-year-zero keeps the rollover
    in one place rather than in sixty subtractions.

    Because periods are zero-padded ``YYYY-MM``, the string order is the
    calendar order — so the result can be compared against a stored period
    directly, in Python or in SQL, without parsing either side.
    """
    year, month = (int(part) for part in period.split("-"))
    index = year * 12 + (month - 1) - count
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def period_start(period: str) -> date:
    """The first day of *period* — the day its return starts being about.

    :func:`period_end`'s counterpart, and needed for the same reason: a rule
    that fires on a particular day belongs to the return for the month that day
    fell in, and deciding which month that was takes both ends of it.
    """
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, 1)


def period_end(period: str) -> date:
    """The last day of *period* — the day its return is a statement about.

    Derived by stepping back a day from the first of the following month, which
    gets February and the leap years right without a table.

    A return covers a month that has closed, so anything computed against a
    clock rather than against a date has to be told which clock: "as of today"
    in a document about a period that ended is a different figure every time it
    is generated. This is the instant such a document is anchored to.
    """
    year, month = (int(part) for part in next_period(period).split("-"))
    return date(year, month, 1) - timedelta(days=1)


def completed_periods(today: date, count: int) -> list[str]:
    """The *count* periods that have ended as of *today*, newest first.

    The month *today* falls in is excluded: a return covers a whole month, and
    the portal does not open it until that month is over. Including it would
    have the product asking for a GSTR-1 covering sales that have not happened.
    """
    period = period_of(today)
    periods: list[str] = []
    for _ in range(count):
        period = previous_period(period)
        periods.append(period)
    return periods


def _due_on(period: str, day: int) -> date:
    """*day* of the month following *period*."""
    year, month = (int(part) for part in next_period(period).split("-"))
    return date(year, month, day)


def gstr1_due_date(period: str) -> date:
    """GSTR-1 due date for *period* — the 11th of the following month."""
    return _due_on(period, GSTR1_DUE_DAY)


def gstr3b_due_date(period: str) -> date:
    """GSTR-3B due date for *period* — the 20th of the following month."""
    return _due_on(period, GSTR3B_DUE_DAY)


# The Indian financial year starts in April. Every annual GST rule is written
# against it rather than the calendar year, so an invoice dated March and one
# dated April are a year apart for the purposes below even though they are a
# month apart on the wall.
FY_START_MONTH = 4

# s.16(4): credit on an invoice may not be taken after the 30th of November
# following the end of the financial year the invoice pertains to. This is the
# one GST deadline that destroys money rather than costing interest — the
# credit is not deferred past it, it is gone — which is why it gets its own
# arithmetic here rather than being derived at a call site.
ITC_CLAIM_DEADLINE_MONTH = 11
ITC_CLAIM_DEADLINE_DAY = 30


def financial_year(moment: date) -> str:
    """The Indian financial year *moment* falls in, as ``YYYY-YY``.

    ``2025-26`` for anything from 1 April 2025 to 31 March 2026. The short
    second half is how the year is written on every Indian tax document, and
    matching that matters more here than being parseable — this string is shown
    to a business, and ``2025-2026`` is not what their accountant writes.
    """
    start = moment.year if moment.month >= FY_START_MONTH else moment.year - 1
    return f"{start:04d}-{(start + 1) % 100:02d}"


def financial_year_end(moment: date) -> date:
    """The last day of the financial year *moment* falls in — 31 March."""
    start = moment.year if moment.month >= FY_START_MONTH else moment.year - 1
    return date(start + 1, FY_START_MONTH, 1) - timedelta(days=1)


def itc_claim_deadline(moment: date) -> date:
    """The day credit on an invoice dated *moment* stops being claimable.

    s.16(4), and the reason a purchase invoice that never reached a return is
    worth alerting about long before anyone thinks of it as late: an invoice
    from April 2025 has until 30 November 2026, so it sits unclaimed for
    nineteen months looking like nothing is wrong, and then the credit is gone
    permanently. There is no late fee for this and no way to take it afterwards.

    The statute's other leg — "or furnishing of the relevant annual return,
    whichever is earlier" — is deliberately not modelled. GSTR-9 is outside
    what this product handles, so it has no way to know that a business filed
    one in September and brought their own deadline forward. That makes this
    date the *outer* bound: the true deadline is never later than it, and is
    earlier for a business that files GSTR-9 before 30 November. Such a
    business has less time than this says, not more, and the alert wording
    says so.
    """
    return date(
        financial_year_end(moment).year,
        ITC_CLAIM_DEADLINE_MONTH,
        ITC_CLAIM_DEADLINE_DAY,
    )


# The returns a business files, and the day each is due. Iterated by the
# alerting, so a return type added here is one the deadline alerts start
# covering without a second edit.
DUE_DAY: dict[ReturnType, int] = {
    ReturnType.GSTR1: GSTR1_DUE_DAY,
    ReturnType.GSTR3B: GSTR3B_DUE_DAY,
}


def due_date(period: str, return_type: ReturnType) -> date:
    """Due date for *return_type* covering *period*.

    Raises :class:`ValueError` for a return the business does not file — see
    the module docstring on why GSTR-2B has no due date.
    """
    try:
        day = DUE_DAY[return_type]
    except KeyError:
        raise ValueError(
            f"{return_type.value} is not a return this business files, so it has "
            "no due date"
        ) from None
    return _due_on(period, day)
