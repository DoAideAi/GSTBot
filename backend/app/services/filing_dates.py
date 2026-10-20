"""Which returns a taxpayer owes for a period, when, and what lateness costs.

:mod:`app.services.gst_calendar` answers this for the two returns the product
itself prepares (monthly GSTR-1 and GSTR-3B). The public deadline checker is
asked about every kind of filer, so this extends it to QRMP quarterly filers,
composition dealers and the annual returns — the same dates the ``/due-dates``
page prints — while still taking the monthly dates from ``gst_calendar`` so a
change there reaches both.

Notified extensions are not modelled. The government extends individual
deadlines by notification, often days before they fall; a checker that baked
one in would be wrong for every later year. Each answer says so.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from app.services import gst_calendar
from app.services import late_fee as late_fee_service


class FilerType(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    COMPOSITION = "composition"


# QRMP filers' GSTR-3B is staggered by state to spread portal load. Category A
# files by the 22nd of the month after the quarter, everyone else by the 24th
# (Notification 01/2021-CT and the rule 61(5) proviso).
CATEGORY_A_STATES = frozenset(
    {"22", "23", "24", "25", "26", "27", "29", "30", "31", "32", "33", "34", "35", "36", "37"}
)

QUARTER_END_MONTHS = frozenset({3, 6, 9, 12})


@dataclass(frozen=True)
class Deadline:
    form: str
    description: str
    covers: str
    due: date
    optional: bool = False
    # Only the two returns whose s.47 fee :mod:`late_fee` models carry one.
    late_fee_applies: bool = False


@dataclass(frozen=True)
class DeadlineStatus:
    deadline: Deadline
    days_remaining: int
    status: str
    late_fee: Decimal | None
    nil_late_fee: Decimal | None


def _on(period: str, day: int) -> date:
    """*day* of the month after *period*."""
    year, month = (int(part) for part in gst_calendar.next_period(period).split("-"))
    return date(year, month, day)


def quarter_end(period: str) -> str:
    year, month = (int(part) for part in period.split("-"))
    return f"{year:04d}-{((month - 1) // 3 + 1) * 3:02d}"


def financial_year_label(period: str) -> str:
    start = gst_calendar.financial_year_end(gst_calendar.period_start(period)).year - 1
    return f"FY {start}-{str(start + 1)[2:]}"


def deadlines(period: str, filer: FilerType, state_code: str | None = None) -> list[Deadline]:
    month = int(period.split("-")[1])
    fy_end = gst_calendar.financial_year_end(gst_calendar.period_start(period))
    fy = financial_year_label(period)
    found: list[Deadline] = []

    if filer is FilerType.COMPOSITION:
        qe = quarter_end(period)
        found.append(Deadline(
            "CMP-08", "Quarterly statement-cum-challan for composition dealers",
            f"quarter ending {qe}", _on(qe, 18),
        ))
        found.append(Deadline(
            "GSTR-4", "Annual return for composition dealers", fy,
            date(fy_end.year, 4, 30),
        ))
        return found

    if filer is FilerType.MONTHLY:
        found.append(Deadline(
            "GSTR-1", "Outward supplies (sales) statement", period,
            gst_calendar.gstr1_due_date(period), late_fee_applies=True,
        ))
        found.append(Deadline(
            "GSTR-3B", "Summary return and tax payment", period,
            gst_calendar.gstr3b_due_date(period), late_fee_applies=True,
        ))
    elif month in QUARTER_END_MONTHS:
        qe = quarter_end(period)
        found.append(Deadline(
            "GSTR-1", "Quarterly outward supplies statement (QRMP)", f"quarter ending {qe}",
            _on(qe, 13), late_fee_applies=True,
        ))
        # Without a state the category is unknown, and picking one would be a
        # confident wrong date for half the country. Both are listed instead.
        categories = (
            [state_code in CATEGORY_A_STATES] if state_code else [True, False]
        )
        for category_a in categories:
            label = ""
            if not state_code:
                label = " — Category A states" if category_a else " — Category B states"
            found.append(Deadline(
                f"GSTR-3B{label}", "Quarterly summary return and tax payment (QRMP)",
                f"quarter ending {qe}", _on(qe, 22 if category_a else 24),
                late_fee_applies=True,
            ))
    else:
        found.append(Deadline(
            "IFF", "Invoice Furnishing Facility for B2B invoices (QRMP, optional)",
            period, _on(period, 13), optional=True,
        ))
        found.append(Deadline(
            "PMT-06", "Monthly tax payment challan (QRMP)", period, _on(period, 25),
        ))

    found.append(Deadline(
        "GSTR-9", "Annual return (GSTR-9C too if turnover exceeds ₹5 crore)", fy,
        date(fy_end.year, 12, 31),
    ))
    return found


def status_of(
    deadline: Deadline, today: date, previous_year_turnover: Decimal | None = None
) -> DeadlineStatus:
    days = (deadline.due - today).days
    status = "due_today" if days == 0 else ("upcoming" if days > 0 else "overdue")
    fee = nil_fee = None
    if deadline.late_fee_applies and days < 0:
        fee = late_fee_service.late_fee(
            -days, is_nil=False, previous_year_turnover=previous_year_turnover
        ).total
        nil_fee = late_fee_service.late_fee(-days, is_nil=True).total
    return DeadlineStatus(deadline, days, status, fee, nil_fee)
