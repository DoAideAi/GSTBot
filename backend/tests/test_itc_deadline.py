"""s.16(4): the deadline that destroys credit rather than deferring it.

Every test here fixes ``as_of``. The whole subject of the module is the
distance between an invoice date and the 30th of November following its
financial year, so a suite that read the clock would assert something
different every morning — and would quietly stop testing the expired branch
altogether once the fixture dates fell behind the wall calendar.

The dates are chosen so two financial years are in play at once with only one
of them at risk:

* 2025-06-10 → FY 2025-26 → deadline 30 Nov 2026
* 2026-05-20 → FY 2026-27 → deadline 30 Nov 2027

and ``AS_OF`` sits exactly sixty days before the first of those, which is the
lead window's boundary. That gives the near year an alert and the far year
none, so a test that accidentally widens the window fails rather than passing
with an extra row nobody looked at.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.business import Business
from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import alerting, gst_calendar, itc_deadline
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
    make_paid,
)

# The near year: an invoice from June 2025, whose credit lapses on 30 Nov 2026.
NEAR_DATE = date(2025, 6, 10)
NEAR_PERIOD = "2025-06"
NEAR_FY = "2025-26"
NEAR_DEADLINE = date(2026, 11, 30)

# The far year: May 2026, lapsing 30 Nov 2027 — outside every window below.
FAR_DATE = date(2026, 5, 20)
FAR_PERIOD = "2026-05"
FAR_FY = "2026-27"
FAR_DEADLINE = date(2027, 11, 30)

# Exactly LEAD_DAYS before NEAR_DEADLINE. On this date the near year is at risk
# and the far year is not.
AS_OF = date(2026, 10, 1)

# Ten days out — inside URGENT_DAYS.
URGENT_AS_OF = date(2026, 11, 20)

# The day after the credit died.
LAPSED_AS_OF = date(2026, 12, 1)

# Long before every period under test, so nothing is withheld for being older
# than the business.
SIGNED_UP = datetime(2025, 4, 2, 10, 0)


def make_business(db, *, gstin=BUSINESS_GSTIN, created=SIGNED_UP) -> Business:
    """A tenant with an explicit signup date.

    ``created_at`` is a server default, so a merely-inserted row gets "now" —
    the real clock, which is years after the periods these tests are about and
    would have ``since_period`` withhold every one of them.
    """
    business = Business(
        gstin=gstin,
        legal_name="Umang Traders Private Limited",
        state_code=gstin[:2],
        created_at=created,
        updated_at=created,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def save_purchase(db, business_id, **kwargs) -> Invoice:
    """A purchase invoice carrying ₹18,000 of IGST credit."""
    defaults = dict(
        business_id=business_id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number="INV-1",
        invoice_date=NEAR_DATE,
        period=NEAR_PERIOD,
        taxable_value=Decimal("100000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("18000.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("118000.00"),
        itc_eligible=True,
        reverse_charge=False,
        is_capital_good=False,
    )
    defaults.update(kwargs)
    invoice = Invoice(**defaults)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def record_3b(db, business, *, period=NEAR_PERIOD, filed_on=date(2025, 7, 20)):
    """Mark the GSTR-3B for one period filed — the only thing that claims credit."""
    row = GSTRReturn(
        business_id=business.id,
        period=period,
        return_type=ReturnType.GSTR3B,
        status=ReturnStatus.FILED,
        filed_at=datetime(filed_on.year, filed_on.month, filed_on.day, 11, 0),
        arn="AA270426000000A",
    )
    db.add(row)
    db.commit()
    return row


def sweep(db, business, *, today=AS_OF):
    result = alerting.sweep_itc_deadlines(db, business, today=today)
    db.commit()
    return result


def itc_alerts(db, business) -> list[Alert]:
    return (
        db.query(Alert)
        .filter_by(business_id=business.id, alert_type=AlertType.ITC_AT_RISK)
        .order_by(Alert.id)
        .all()
    )


def one_itc_alert(db, business) -> Alert:
    rows = itc_alerts(db, business)
    assert len(rows) == 1, f"expected exactly one ITC alert, got {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# The calendar arithmetic the deadline is derived from
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (date(2025, 4, 1), "2025-26"),   # first day of a financial year
        (date(2026, 3, 31), "2025-26"),  # last day of the same one
        (date(2026, 4, 1), "2026-27"),   # the day it rolls over
        (date(2025, 12, 31), "2025-26"),  # the calendar year rolling does not
    ],
)
def test_the_financial_year_runs_april_to_march_not_january_to_december(moment, expected):
    assert gst_calendar.financial_year(moment) == expected


def test_a_march_invoice_and_an_april_invoice_are_a_year_apart_for_s_16_4():
    """One month apart on the wall, two different deadlines in the statute."""
    march = gst_calendar.itc_claim_deadline(date(2026, 3, 31))
    april = gst_calendar.itc_claim_deadline(date(2026, 4, 1))

    assert march == date(2026, 11, 30)
    assert april == date(2027, 11, 30)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (date(2025, 4, 1), date(2026, 3, 31)),
        (date(2026, 3, 31), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2027, 3, 31)),
    ],
)
def test_the_financial_year_ends_on_the_thirty_first_of_march(moment, expected):
    assert gst_calendar.financial_year_end(moment) == expected


def test_a_leap_year_february_invoice_still_lands_on_the_thirtieth_of_november():
    """29 February exists only in the FY-end arithmetic; the deadline is fixed."""
    assert gst_calendar.itc_claim_deadline(date(2024, 2, 29)) == date(2024, 11, 30)


# ---------------------------------------------------------------------------
# What the section has anything to say about
# ---------------------------------------------------------------------------

def test_credit_that_was_never_claimable_cannot_lapse(db_session):
    """s.17(5)-blocked credit loses nothing on 30 November — it had nothing."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, itc_eligible=False)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_a_reverse_charge_purchase_is_left_alone(db_session):
    """The document s.16(4) runs against is the recipient's own, which is not held."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, reverse_charge=True)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_an_invoice_with_no_date_gets_no_invented_deadline(db_session):
    """No date, no financial year, so no alarming figure attached to a guess."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, invoice_date=None)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_capital_goods_are_included_even_though_the_itc_summary_excludes_them(db_session):
    """Rule 43 apportions the credit; s.16(4) still bounds when it may be taken."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, is_capital_good=True)

    rows = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert [row.financial_year for row in rows] == [NEAR_FY]
    assert rows[0].total == Decimal("18000.00")


def test_a_sale_is_not_a_purchase_and_carries_no_input_credit(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id, invoice_type=InvoiceType.SALES)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


# ---------------------------------------------------------------------------
# lapsing_credit — what is unclaimed, and for how much longer
# ---------------------------------------------------------------------------

def test_a_business_with_no_purchases_has_nothing_at_risk(db_session):
    """The empty list means "nothing at risk", so a caller can say exactly that."""
    business = make_business(db_session)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_unclaimed_credit_is_reported_against_its_financial_years_deadline(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert row.financial_year == NEAR_FY
    assert row.deadline == NEAR_DEADLINE
    assert row.days_remaining == itc_deadline.LEAD_DAYS
    assert row.invoice_count == 1
    assert row.periods == (NEAR_PERIOD,)
    assert row.total == Decimal("18000.00")
    assert row.expired is False


def test_a_lapsing_row_cannot_be_edited_after_it_is_reported(db_session):
    """One row answers two readers, and neither recomputes it.

    ``lapsing_credit`` is called once and its rows go to the ``/itc/lapsing``
    endpoint and to the alert the sweep raises — which reads ``total`` into the
    message body a business is emailed. A reader that adjusted a row in place
    would change the figure the other one announced, and nothing further down
    re-derives it from the invoices to disagree.
    """
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    with pytest.raises(dataclasses.FrozenInstanceError):
        row.days_remaining = 0


def test_recording_the_gstr_3b_takes_the_credit_and_empties_the_list(db_session):
    """Credit reaches a return through 3B table 4(A); nothing else claims it."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    record_3b(db_session, business)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_a_filed_gstr_1_does_not_claim_input_credit(db_session):
    """GSTR-1 is an outward return. Filing it says nothing about credit taken."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    db_session.add(
        GSTRReturn(
            business_id=business.id,
            period=NEAR_PERIOD,
            return_type=ReturnType.GSTR1,
            status=ReturnStatus.FILED,
            filed_at=datetime(2025, 7, 11, 11, 0),
            arn="AA270426000000B",
        )
    )
    db_session.commit()

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)
    assert row.financial_year == NEAR_FY


def test_a_matched_invoice_is_not_a_claimed_one(db_session):
    """Matching says the supplier declared it, not that the buyer took it."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, status=InvoiceStatus.MATCHED)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)
    assert row.invoice_count == 1


def test_two_invoices_in_one_year_become_one_row_with_the_tax_summed(db_session):
    """One row per year, not per invoice: a business wants a number and a date."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, invoice_number="INV-1")
    save_purchase(
        db_session,
        business.id,
        invoice_number="INV-2",
        invoice_date=date(2025, 8, 4),
        period="2025-08",
        igst=Decimal("2000.00"),
    )

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert row.invoice_count == 2
    assert row.total == Decimal("20000.00")
    assert row.periods == (NEAR_PERIOD, "2025-08")


def test_the_intra_state_split_is_summed_under_its_own_heads(db_session):
    business = make_business(db_session)
    save_purchase(
        db_session,
        business.id,
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
        cess=Decimal("500.00"),
    )

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert row.tax.cgst == Decimal("9000.00")
    assert row.tax.sgst == Decimal("9000.00")
    assert row.tax.cess == Decimal("500.00")
    assert row.total == Decimal("18500.00")


def test_years_are_ordered_by_deadline_so_the_soonest_loss_is_first(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id, invoice_date=FAR_DATE, period=FAR_PERIOD)
    save_purchase(db_session, business.id, invoice_number="INV-2")

    rows = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert [row.financial_year for row in rows] == [NEAR_FY, FAR_FY]
    assert [row.deadline for row in rows] == [NEAR_DEADLINE, FAR_DEADLINE]


def test_the_period_is_derived_from_the_date_when_the_column_is_empty(db_session):
    """Otherwise the row is unattributable and no filing could ever clear it."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, period=None)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)
    assert row.periods == (NEAR_PERIOD,)


def test_filing_clears_an_invoice_whose_period_column_was_never_populated(db_session):
    """The derived period is the one the filing has to match, or the alert sticks."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, period=None)
    record_3b(db_session, business)

    assert itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF) == []


def test_a_lapsed_year_stays_on_the_list_rather_than_disappearing(db_session):
    """The permanent loss is the most important row, not one to drop overnight."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=LAPSED_AS_OF)

    assert row.expired is True
    assert row.days_remaining == -1


def test_a_period_from_before_the_business_signed_up_is_withheld(db_session):
    """"You have lost ₹4 lakh" is the worst thing to be wrong about on day one."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    assert (
        itc_deadline.lapsing_credit(
            db_session, business.id, as_of=AS_OF, since_period="2025-07"
        )
        == []
    )


def test_the_floor_is_inclusive_of_the_period_the_business_arrived_in(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    rows = itc_deadline.lapsing_credit(
        db_session, business.id, as_of=AS_OF, since_period=NEAR_PERIOD
    )
    assert [row.financial_year for row in rows] == [NEAR_FY]


def test_one_tenants_unclaimed_credit_is_invisible_to_another(db_session):
    business = make_business(db_session)
    rival = make_business(db_session, gstin="29AAGCB7383J1Z4")
    save_purchase(db_session, business.id)

    assert itc_deadline.lapsing_credit(db_session, rival.id, as_of=AS_OF) == []


def test_the_serialised_row_carries_the_deadline_as_an_iso_date(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)

    assert row.as_dict() == {
        "financial_year": NEAR_FY,
        "deadline": "2026-11-30",
        "days_remaining": 60,
        "expired": False,
        "tax": row.tax.as_dict(),
        "invoice_count": 1,
        "periods": [NEAR_PERIOD],
    }


# ---------------------------------------------------------------------------
# at_risk — the subset worth interrupting someone about
# ---------------------------------------------------------------------------

def test_a_year_with_more_than_the_lead_window_left_is_not_yet_worth_raising(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    assert itc_deadline.at_risk(db_session, business.id, as_of=date(2026, 9, 30)) == []


def test_the_lead_window_boundary_is_inclusive(db_session):
    """Sixty days out is inside; sixty-one is not. Asserted from both sides."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=AS_OF)
    assert row.days_remaining == itc_deadline.LEAD_DAYS


def test_a_lapsed_year_is_still_at_risk_so_the_alert_can_say_it_happened(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=LAPSED_AS_OF)
    assert row.expired is True


def test_at_risk_hides_the_far_year_the_full_list_still_shows(db_session):
    """The screen shows the shape of it; the alerting only sees what is nearly gone."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    save_purchase(
        db_session, business.id, invoice_number="INV-2",
        invoice_date=FAR_DATE, period=FAR_PERIOD,
    )

    everything = itc_deadline.lapsing_credit(db_session, business.id, as_of=AS_OF)
    interrupting = itc_deadline.at_risk(db_session, business.id, as_of=AS_OF)

    assert [row.financial_year for row in everything] == [NEAR_FY, FAR_FY]
    assert [row.financial_year for row in interrupting] == [NEAR_FY]


# ---------------------------------------------------------------------------
# The wording and the severity ladder
# ---------------------------------------------------------------------------

def test_the_alert_names_the_amount_the_date_and_what_to_file(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=AS_OF)

    title, message = alerting.itc_wording(row)

    assert title == f"Input credit for {NEAR_FY} lapses in 60 days"
    assert "₹18,000" in message
    assert "2026-11-30" in message
    assert NEAR_PERIOD in message


def test_the_last_day_says_today_rather_than_in_zero_days(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=NEAR_DEADLINE)

    title, _ = alerting.itc_wording(row)
    assert title == f"Input credit for {NEAR_FY} lapses today"


def test_one_day_left_is_singular(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=date(2026, 11, 29))

    title, _ = alerting.itc_wording(row)
    assert title == f"Input credit for {NEAR_FY} lapses in 1 day"


def test_a_lapsed_year_is_not_told_it_can_still_be_saved_by_hurrying(db_session):
    """There is no discretion left, and wording implying otherwise would be cruel."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=LAPSED_AS_OF)

    title, message = alerting.itc_wording(row)

    assert title == f"Input credit for {NEAR_FY} has lapsed"
    assert "can no longer be claimed" in message
    # The one thing still worth doing: the product only knows about filings it
    # was told about, so it says so rather than asserting the loss outright.
    assert "record them here" in message


def test_the_rupee_figure_is_grouped_the_way_a_business_reads_it(db_session):
    """Indian grouping, and no paise on a figure this size."""
    business = make_business(db_session)
    save_purchase(db_session, business.id, igst=Decimal("142318.49"))
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=AS_OF)

    _, message = alerting.itc_wording(row)
    assert "₹142,318" in message
    assert "142318.49" not in message


def test_a_single_invoice_is_not_described_as_invoices(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=AS_OF)

    _, message = alerting.itc_wording(row)
    assert "1 purchase invoice " in message


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (AS_OF, AlertSeverity.INFO),            # sixty days out
        (URGENT_AS_OF, AlertSeverity.WARNING),  # ten days out
        (LAPSED_AS_OF, AlertSeverity.CRITICAL),  # gone
    ],
)
def test_the_severity_climbs_as_the_deadline_approaches(db_session, as_of, expected):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=as_of)

    assert alerting._itc_severity(row) is expected


def test_the_urgent_boundary_is_inclusive(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    fifteen_days_out = date(2026, 11, 15)
    (row,) = itc_deadline.at_risk(db_session, business.id, as_of=fifteen_days_out)

    assert row.days_remaining == itc_deadline.URGENT_DAYS
    assert alerting._itc_severity(row) is AlertSeverity.WARNING


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def test_the_sweep_raises_one_alert_for_the_year_at_risk(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    result = sweep(db_session, business)

    alert = one_itc_alert(db_session, business)
    assert result.raised == 1
    assert alert.severity is AlertSeverity.INFO
    assert alert.status is AlertStatus.PENDING
    assert alert.due_date == NEAR_DEADLINE
    assert alert.context["financial_year"] == NEAR_FY
    assert alert.context["amount"] == "18000.00"
    assert alert.context["invoice_count"] == 1
    assert alert.context["periods"] == [NEAR_PERIOD]


def test_the_lapse_alert_carries_no_period_because_it_covers_a_year(db_session):
    """A financial year is not a ``YYYY-MM``; putting one there breaks the filter."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)

    assert one_itc_alert(db_session, business).period is None


def test_sweeping_twice_in_a_day_does_not_raise_the_alert_twice(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    sweep(db_session, business)
    second = sweep(db_session, business)

    assert second.raised == 0
    assert len(itc_alerts(db_session, business)) == 1


def test_a_dismissed_alert_is_not_raised_again_the_next_morning(db_session):
    """Dismissal is the business saying "I know"; a copy would be nagging."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    one_itc_alert(db_session, business).status = AlertStatus.DISMISSED
    db_session.commit()

    result = sweep(db_session, business, today=date(2026, 10, 2))

    assert result.raised == 0
    assert one_itc_alert(db_session, business).status is AlertStatus.DISMISSED


def test_dismissing_sixty_days_out_is_not_consent_to_never_hear_it_lapsed(db_session):
    """The escalation to CRITICAL reopens what was dismissed as a distant problem."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    one_itc_alert(db_session, business).status = AlertStatus.DISMISSED
    db_session.commit()

    result = sweep(db_session, business, today=LAPSED_AS_OF)

    alert = one_itc_alert(db_session, business)
    assert result.reopened == 1
    assert alert.status is AlertStatus.PENDING
    assert alert.severity is AlertSeverity.CRITICAL
    assert alert.title == f"Input credit for {NEAR_FY} has lapsed"


def test_an_alert_read_and_then_escalated_counts_as_open_again(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    one_itc_alert(db_session, business).status = AlertStatus.READ
    db_session.commit()

    sweep(db_session, business, today=URGENT_AS_OF)

    alert = one_itc_alert(db_session, business)
    assert alert.status is AlertStatus.PENDING
    assert alert.severity is AlertSeverity.WARNING


def test_the_amount_is_rewritten_as_more_unclaimed_invoices_arrive(db_session):
    """"₹18,000" is wrong the moment a second purchase lands in the same year."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    save_purchase(
        db_session, business.id, invoice_number="INV-2", igst=Decimal("2000.00")
    )

    sweep(db_session, business, today=date(2026, 10, 2))

    alert = one_itc_alert(db_session, business)
    assert alert.context["amount"] == "20000.00"
    assert alert.context["invoice_count"] == 2
    assert "₹20,000" in alert.message


def test_recording_the_missing_return_closes_the_alert(db_session):
    """The credit is safe; there is nothing further to ask for."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    record_3b(db_session, business)

    result = sweep(db_session, business, today=date(2026, 10, 2))

    assert result.resolved == 1
    assert one_itc_alert(db_session, business).status is AlertStatus.RESOLVED


def test_recording_the_return_after_the_deadline_still_closes_the_alert(db_session):
    """Late or not, the alert asked for a filing and the filing happened."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business, today=LAPSED_AS_OF)
    record_3b(db_session, business, filed_on=date(2026, 12, 2))

    result = sweep(db_session, business, today=date(2026, 12, 3))

    assert result.resolved == 1
    assert one_itc_alert(db_session, business).status is AlertStatus.RESOLVED


def test_a_dismissed_alert_is_not_counted_as_resolved_when_the_year_clears(db_session):
    """It was already closed. Counting it again would inflate what the sweep did."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    one_itc_alert(db_session, business).status = AlertStatus.DISMISSED
    db_session.commit()
    record_3b(db_session, business)

    result = sweep(db_session, business, today=date(2026, 10, 2))

    assert result.resolved == 0
    assert one_itc_alert(db_session, business).status is AlertStatus.DISMISSED


def test_a_return_recorded_and_then_unrecorded_brings_the_alert_back(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    filing = record_3b(db_session, business)
    sweep(db_session, business, today=date(2026, 10, 2))

    filing.deleted_at = datetime(2026, 10, 3, 9, 0)
    db_session.commit()
    result = sweep(db_session, business, today=date(2026, 10, 3))

    assert result.reopened == 1
    assert one_itc_alert(db_session, business).status is AlertStatus.PENDING


def test_the_far_year_gets_no_alert_until_it_enters_the_lead_window(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id, invoice_date=FAR_DATE, period=FAR_PERIOD)

    assert sweep(db_session, business).raised == 0
    assert itc_alerts(db_session, business) == []


def test_two_years_at_risk_get_one_alert_each(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    save_purchase(
        db_session, business.id, invoice_number="INV-2",
        invoice_date=FAR_DATE, period=FAR_PERIOD,
    )

    # Late enough that both deadlines are inside the lead window.
    result = sweep(db_session, business, today=date(2027, 10, 1))

    assert result.raised == 2
    assert {a.context["financial_year"] for a in itc_alerts(db_session, business)} == {
        NEAR_FY,
        FAR_FY,
    }


def test_a_business_is_not_told_about_credit_from_before_it_signed_up(db_session):
    business = make_business(db_session, created=datetime(2026, 9, 20, 10, 0))
    save_purchase(db_session, business.id)

    assert sweep(db_session, business).raised == 0


def test_an_alert_whose_context_lost_its_year_is_not_matched_against(db_session):
    """A row that cannot say which year it covers must not shadow a real one."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    db_session.add(
        Alert(
            business_id=business.id,
            alert_type=AlertType.ITC_AT_RISK,
            severity=AlertSeverity.INFO,
            status=AlertStatus.PENDING,
            title="Stale",
            message="Stale",
            context={},
        )
    )
    db_session.commit()

    result = sweep(db_session, business)

    assert result.raised == 1
    assert len(itc_alerts(db_session, business)) == 2


def test_a_soft_deleted_alert_does_not_suppress_a_fresh_one(db_session):
    business = make_business(db_session)
    save_purchase(db_session, business.id)
    sweep(db_session, business)
    alert = one_itc_alert(db_session, business)
    alert.deleted_at = datetime(2026, 10, 2, 9, 0)
    db_session.commit()

    result = sweep(db_session, business, today=date(2026, 10, 3))

    assert result.raised == 1


def test_the_daily_sweep_covers_s_16_4_as_well_as_the_filing_deadlines(db_session):
    """The two passes share a result, so a caller sees one count for the tenant."""
    business = make_business(db_session)
    save_purchase(db_session, business.id)

    result = alerting.sweep_business(db_session, business, today=AS_OF)
    db_session.commit()

    assert result.raised >= 1
    assert len(itc_alerts(db_session, business)) == 1


def test_the_s_16_4_pass_runs_even_when_the_filing_window_is_empty(db_session):
    """Its deadline is nineteen months behind the invoice, long out of that window."""
    business = make_business(db_session, created=datetime(2026, 10, 1, 9, 0))
    save_purchase(db_session, business.id)

    # Signed up today, so no completed period is inside the filing sweep's
    # window — and the s.16(4) row is withheld too, for the same signup reason.
    result = alerting.sweep_business(db_session, business, today=AS_OF)
    db_session.commit()

    assert result.businesses == 1
    assert itc_alerts(db_session, business) == []


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------

def test_the_lapsing_endpoint_reports_the_years_and_their_totals(
    auth_client, db_session, paid_business
):
    business = paid_business
    save_purchase(db_session, business.id)

    response = auth_client.get(f"/api/v1/itc/lapsing?as_of={AS_OF.isoformat()}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lead_days"] == itc_deadline.LEAD_DAYS
    assert body["total_at_risk"] == "18000.00"
    assert body["total_expired"] == "0"
    (year,) = body["years"]
    assert year["financial_year"] == NEAR_FY
    assert year["deadline"] == "2026-11-30"
    assert year["days_remaining"] == 60
    assert year["expired"] is False
    assert year["periods"] == [NEAR_PERIOD]


def test_the_endpoint_separates_what_is_lost_from_what_is_still_savable(
    auth_client, db_session, paid_business
):
    business = paid_business
    save_purchase(db_session, business.id)
    save_purchase(
        db_session, business.id, invoice_number="INV-2",
        invoice_date=FAR_DATE, period=FAR_PERIOD, igst=Decimal("5000.00"),
    )

    response = auth_client.get(f"/api/v1/itc/lapsing?as_of={LAPSED_AS_OF.isoformat()}")

    body = response.json()
    assert body["total_expired"] == "18000.00"
    assert body["total_at_risk"] == "5000.00"


def test_the_endpoint_shows_years_from_before_signup_that_the_alerting_withholds(
    auth_client, db_session, paid_business
):
    business = paid_business
    """Nobody is being interrupted here — the business asked."""
    save_purchase(db_session, business.id, invoice_date=date(2019, 6, 10), period="2019-06")

    response = auth_client.get(f"/api/v1/itc/lapsing?as_of={AS_OF.isoformat()}")

    assert [y["financial_year"] for y in response.json()["years"]] == ["2019-20"]


def test_the_endpoint_says_nothing_is_at_risk_rather_than_failing(auth_client, paid_business):
    response = auth_client.get("/api/v1/itc/lapsing")

    assert response.status_code == 200
    assert response.json() == {
        "years": [],
        "total_at_risk": "0",
        "total_expired": "0",
        "lead_days": itc_deadline.LEAD_DAYS,
    }


def test_the_lapsing_endpoint_refuses_an_unparseable_as_of(auth_client, paid_business):
    assert auth_client.get("/api/v1/itc/lapsing?as_of=never").status_code == 422


def test_one_tenant_cannot_read_anothers_lapsing_credit(
    auth_client, db_session, business, other_tenant
):
    save_purchase(db_session, business.id)
    # The rival is paid too, so the empty answer is the isolation, not the paywall.
    rival = db_session.query(Business).filter_by(gstin=SUPPLIER_GSTIN_SAME_STATE).one()
    make_paid(db_session, rival.id)

    auth_client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    response = auth_client.get(f"/api/v1/itc/lapsing?as_of={AS_OF.isoformat()}")

    assert response.status_code == 200
    assert response.json()["years"] == []


# ---------------------------------------------------------------------------
# What the answer costs to produce
# ---------------------------------------------------------------------------

class TestTheSweepDoesNotReadTheMonthsItHasAlreadySettled:
    """The register grows with the customer's history; the answer does not.

    ``lapsing_credit`` is asked once per tenant by the daily alert sweep, so
    what it reads out of the invoices table is multiplied by the whole customer
    list. Every invoice from a period whose GSTR-3B is recorded as filed is
    discarded, and a business that files on time has filed all but the current
    month — so reading the register whole meant loading a year of rows to keep
    the handful the alert could possibly be about.

    A claim about the shape rather than a number: the same unfiled month costs
    the same whether one month has been filed behind it or twelve. A constant
    would only be a claim about today's fixtures.
    """

    def _rows_loaded(self, db, business, **kwargs) -> int:
        """How many invoice rows one call hydrates.

        Rows rather than statements: the query count is the same before and
        after this change and it is the width of the read that grew. Counted
        as the ORM makes each instance persistent rather than by inspecting
        the session afterwards, because the identity map holds weak references
        — the invoices are unreachable the moment the call returns, and a
        count taken after it is a count of whatever has not been collected yet.

        ``expunge_all`` first for the reason ``tests/test_dashboard.py`` gives:
        the client shares this session, so a row already in the identity map is
        answered from memory and never loads at all.
        """
        # Read before expunging: detaching the fixture's own Business would
        # otherwise make ``business.id`` a lazy load against a session it is
        # no longer in.
        business_id = business.id
        db.expunge_all()

        loaded = []

        def _seen(_session, instance):
            if isinstance(instance, Invoice):
                loaded.append(instance.id)

        event.listen(db, "loaded_as_persistent", _seen)
        try:
            itc_deadline.lapsing_credit(db, business_id, **kwargs)
        finally:
            event.remove(db, "loaded_as_persistent", _seen)
        return len(loaded)

    def _history(self, db, business, months: list[tuple[str, date]], *, filed: bool):
        for index, (period, when) in enumerate(months):
            save_purchase(
                db,
                business.id,
                invoice_number=f"HIST-{index}",
                invoice_date=when,
                period=period,
            )
            if filed:
                record_3b(db, business, period=period, filed_on=when)

    def test_a_filed_month_behind_the_unfiled_one_is_never_loaded(
        self, db_session, business
    ):
        save_purchase(db_session, business.id)  # NEAR_PERIOD, unfiled.
        self._history(
            db_session, business, [("2025-07", date(2025, 7, 11))], filed=True
        )

        assert self._rows_loaded(db_session, business, as_of=AS_OF) == 1

    def test_twelve_filed_months_cost_no_more_than_one(self, db_session, business):
        save_purchase(db_session, business.id)  # NEAR_PERIOD, unfiled.
        self._history(
            db_session,
            business,
            [(f"2025-{month:02d}", date(2025, month, 11)) for month in range(7, 13)]
            + [(f"2026-{month:02d}", date(2026, month, 11)) for month in range(1, 7)],
            filed=True,
        )

        assert self._rows_loaded(db_session, business, as_of=AS_OF) == 1

    def test_an_unfiled_month_is_still_read_however_many_there_are(
        self, db_session, business
    ):
        # The other direction, so the test above cannot be satisfied by a
        # query that reads nothing: what the sweep is actually for still
        # arrives, and arrives whole.
        save_purchase(db_session, business.id)
        self._history(
            db_session,
            business,
            [(f"2025-{month:02d}", date(2025, month, 11)) for month in range(7, 13)],
            filed=False,
        )

        assert self._rows_loaded(db_session, business, as_of=AS_OF) == 7

    def test_a_row_with_no_period_of_its_own_is_still_read(self, db_session, business):
        # Its month is derived from the invoice date in Python, so the query
        # cannot decide it and must not exclude it. This is the row that would
        # disappear if the period filter were pushed down without the null arm.
        record_3b(db_session, business, period=NEAR_PERIOD)
        save_purchase(db_session, business.id, period=None)

        assert self._rows_loaded(db_session, business, as_of=AS_OF) == 1

    def test_a_period_before_the_business_arrived_is_not_read_either(
        self, db_session, business
    ):
        # ``since_period`` is the alerting's guard against announcing a loss
        # from before the product had any record. It bounded the answer;
        # bounding the query too is free.
        save_purchase(
            db_session, business.id, invoice_date=date(2019, 6, 10), period="2019-06"
        )
        save_purchase(db_session, business.id, invoice_number="INV-2")

        loaded = self._rows_loaded(
            db_session, business, as_of=AS_OF, since_period=NEAR_PERIOD
        )
        assert loaded == 1
