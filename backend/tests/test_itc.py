"""The set-off waterfall, the reversal rules, and the ITC endpoints."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.services import filing, gst_calendar, reconciliation
from app.services import itc as itc_service
from app.services.gstr2b import GSTR2BRecord
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE

PERIOD = "2026-04"


def heads(igst="0", cgst="0", sgst="0", cess="0") -> itc_service.TaxHeads:
    return itc_service.TaxHeads(
        igst=Decimal(igst), cgst=Decimal(cgst), sgst=Decimal(sgst), cess=Decimal(cess)
    )


def purchase(**kwargs) -> Invoice:
    """An unsaved purchase invoice with credit on it."""
    defaults = dict(
        id=kwargs.pop("id", 1),
        business_id=1,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number="INV-1",
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        taxable_value=Decimal("100000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("18000.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("118000.00"),
        itc_eligible=True,
        reverse_charge=False,
        is_capital_good=False,
        paid_at=None,
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def save(db, business_id, **kwargs) -> Invoice:
    invoice = purchase(id=None, business_id=business_id, **kwargs)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


# ---------------------------------------------------------------------------
# Section 49 / 49A / 49B — the set-off order
# ---------------------------------------------------------------------------

def test_a_tax_heads_total_is_all_four_heads_added():
    """Every figure this module reports is read through ``.total``.

    Four distinct amounts rather than a round number in one head: cess is the
    one that is zero in almost every fixture here — it applies to a handful of
    goods — so a total that quietly dropped or subtracted it would agree with
    the rest of the suite and be wrong only for the businesses that sell them.
    """
    assert heads(igst="1", cgst="20", sgst="300", cess="4000").total == Decimal("4321")


def test_igst_credit_settles_igst_first():
    result = itc_service.set_off(heads(igst="10000"), heads(igst="10000"))

    assert result.cash_payable.total == Decimal("0.00")
    assert result.credit_carried_forward.total == Decimal("0.00")
    assert [(s.credit_head, s.liability_head) for s in result.steps] == [("igst", "igst")]


def test_igst_credit_spills_onto_cgst_then_sgst():
    """s.49A: IGST must be exhausted before any other credit is touched."""
    result = itc_service.set_off(
        heads(igst="30000"), heads(igst="10000", cgst="10000", sgst="10000")
    )

    assert result.cash_payable.total == Decimal("0.00")
    assert [(s.credit_head, s.liability_head, s.amount) for s in result.steps] == [
        ("igst", "igst", Decimal("10000.00")),
        ("igst", "cgst", Decimal("10000.00")),
        ("igst", "sgst", Decimal("10000.00")),
    ]


def test_cgst_credit_never_settles_sgst_liability():
    """The two are levied by different governments and never meet.

    The business has exactly enough credit in total, and still has to pay the
    SGST in cash while the CGST credit carries forward. Reporting a set-off
    here would understate the cash they have to find this month.
    """
    result = itc_service.set_off(heads(cgst="5000"), heads(sgst="5000"))

    assert result.steps == []
    assert result.cash_payable.sgst == Decimal("5000.00")
    assert result.credit_carried_forward.cgst == Decimal("5000.00")


def test_sgst_credit_never_settles_cgst_liability():
    result = itc_service.set_off(heads(sgst="5000"), heads(cgst="5000"))

    assert result.steps == []
    assert result.cash_payable.cgst == Decimal("5000.00")
    assert result.credit_carried_forward.sgst == Decimal("5000.00")


def test_cgst_credit_settles_its_own_head_then_igst():
    result = itc_service.set_off(heads(cgst="10000"), heads(cgst="4000", igst="3000"))

    assert [(s.credit_head, s.liability_head, s.amount) for s in result.steps] == [
        ("cgst", "cgst", Decimal("4000.00")),
        ("cgst", "igst", Decimal("3000.00")),
    ]
    assert result.credit_carried_forward.cgst == Decimal("3000.00")
    assert result.cash_payable.total == Decimal("0.00")


def test_cess_is_ring_fenced():
    """Cess credit settles cess and nothing else, in either direction."""
    result = itc_service.set_off(heads(cess="5000"), heads(igst="5000"))

    assert result.steps == []
    assert result.cash_payable.igst == Decimal("5000.00")
    assert result.credit_carried_forward.cess == Decimal("5000.00")


def test_igst_is_exhausted_before_cgst_credit_is_used():
    """The rule most often got wrong: using CGST first looks equivalent.

    With ₹10,000 IGST credit and ₹10,000 CGST credit against a ₹10,000 CGST
    liability, the IGST must go first — leaving the CGST credit to carry
    forward, where it can settle a future CGST or IGST liability. Spending the
    CGST credit instead would strand IGST credit that is more flexible.
    """
    result = itc_service.set_off(heads(igst="10000", cgst="10000"), heads(cgst="10000"))

    assert [(s.credit_head, s.liability_head) for s in result.steps] == [("igst", "cgst")]
    assert result.credit_used.igst == Decimal("10000.00")
    assert result.credit_used.cgst == Decimal("0.00")
    assert result.credit_carried_forward.cgst == Decimal("10000.00")


def test_igst_goes_where_the_heads_own_credit_cannot_reach():
    """Rule 88A lets the taxpayer split IGST between CGST and SGST.

    ₹10,000 IGST and ₹10,000 CGST credit against ₹10,000 each of CGST and SGST
    settles in full only if the IGST covers the SGST — CGST credit can never
    reach it. Sending the IGST to CGST first, as this used to, reported
    ₹10,000 of SGST payable in cash with ₹10,000 of CGST credit stranded.
    """
    result = itc_service.set_off(
        heads(igst="10000", cgst="10000"), heads(cgst="10000", sgst="10000")
    )

    assert result.total_cash == Decimal("0.00")
    assert [(s.credit_head, s.liability_head, s.amount) for s in result.steps] == [
        ("igst", "sgst", Decimal("10000.00")),
        ("cgst", "cgst", Decimal("10000.00")),
    ]
    assert result.credit_carried_forward.total == Decimal("0.00")


def test_the_mirror_case_sends_igst_to_cgst():
    result = itc_service.set_off(
        heads(igst="6000", sgst="10000"), heads(cgst="6000", sgst="10000")
    )

    assert result.total_cash == Decimal("0.00")
    assert result.credit_used.igst == Decimal("6000.00")
    assert result.credit_used.sgst == Decimal("10000.00")


def test_igst_beyond_the_shortfalls_is_still_spent_before_other_credit():
    """s.49A: leftover IGST settles the rest of either head before own credit."""
    result = itc_service.set_off(
        heads(igst="15000", cgst="10000"), heads(cgst="10000", sgst="10000")
    )

    assert result.total_cash == Decimal("0.00")
    # 10,000 to the SGST nothing else could pay, the other 5,000 onto CGST.
    assert [(s.credit_head, s.liability_head, s.amount) for s in result.steps] == [
        ("igst", "cgst", Decimal("5000.00")),
        ("igst", "sgst", Decimal("10000.00")),
        ("cgst", "cgst", Decimal("5000.00")),
    ]
    assert result.credit_carried_forward.cgst == Decimal("5000.00")


def test_igst_short_of_both_shortfalls_leaves_the_same_cash_either_way():
    result = itc_service.set_off(heads(igst="4000"), heads(cgst="5000", sgst="5000"))

    assert result.total_cash == Decimal("6000.00")
    assert result.credit_used.igst == Decimal("4000.00")


def test_insufficient_credit_leaves_the_balance_payable_in_cash():
    result = itc_service.set_off(heads(igst="3000"), heads(igst="10000"))

    assert result.cash_payable.igst == Decimal("7000.00")
    assert result.total_cash == Decimal("7000.00")
    assert result.credit_carried_forward.total == Decimal("0.00")


def test_no_liability_carries_the_whole_credit_forward():
    result = itc_service.set_off(heads(igst="1000", cgst="500", sgst="500"), heads())

    assert result.total_cash == Decimal("0.00")
    assert result.credit_carried_forward.total == Decimal("2000.00")


# ---------------------------------------------------------------------------
# Rule 37 — 180 days
# ---------------------------------------------------------------------------

def test_rule_37_flags_an_unpaid_invoice_past_180_days():
    invoice = purchase(invoice_date=date(2026, 1, 1))
    result = itc_service.rule_37([invoice], as_of=date(2026, 7, 1))

    assert [item.invoice_id for item in result.overdue] == [1]
    assert result.reversal.igst == Decimal("18000.00")
    assert result.overdue[0].days_outstanding == 181


def test_rule_37_allows_the_whole_of_day_180():
    """Exactly 180 days is inside the window; 181 is not."""
    invoice = purchase(invoice_date=date(2026, 1, 1))

    on_the_day = itc_service.rule_37([invoice], as_of=date(2026, 6, 30))
    the_day_after = itc_service.rule_37([invoice], as_of=date(2026, 7, 1))

    assert on_the_day.overdue == []
    assert on_the_day.reversal.total == Decimal("0.00")
    assert len(the_day_after.overdue) == 1


def test_rule_37_warns_before_the_deadline():
    invoice = purchase(invoice_date=date(2026, 1, 1))
    # Day 160: twenty days left, inside the thirty-day warning window.
    result = itc_service.rule_37([invoice], as_of=date(2026, 6, 10))

    assert result.overdue == []
    assert [item.invoice_id for item in result.approaching] == [1]
    assert result.approaching[0].days_remaining == 20
    assert result.approaching_amount.igst == Decimal("18000.00")


def test_rule_37_ignores_a_paid_invoice():
    invoice = purchase(invoice_date=date(2026, 1, 1), paid_at=date(2026, 2, 1))
    result = itc_service.rule_37([invoice], as_of=date(2026, 12, 1))

    assert result.overdue == []
    assert result.reversal.total == Decimal("0.00")


class TestPaymentIsJudgedAsOfTheDateAsked:
    """A payment that had not happened yet cannot have stopped the clock.

    ``as_of`` is not a display preference. :func:`filing.build_gstr3b` anchors
    it to the close of the period so that re-generating a closed month's return
    reproduces it — and ``paid_at`` read as a plain flag broke exactly that:
    paying the supplier in February deleted the reversal out of January's 3B,
    a return already filed with it. Under-reversed credit is over-claimed
    credit, and it carries interest.
    """

    # Dated 15 June 2025, so the 180 days run out on 12 December and the
    # reversal belongs to the 2025-12 return.
    LAPSED = date(2025, 6, 15)
    PERIOD_CLOSE = date(2025, 12, 31)

    def test_a_payment_after_the_period_does_not_erase_its_reversal(self):
        invoice = purchase(invoice_date=self.LAPSED, paid_at=date(2026, 1, 20))

        result = itc_service.rule_37([invoice], as_of=self.PERIOD_CLOSE)

        assert [item.invoice_id for item in result.overdue] == [1]
        assert result.reversal_in("2025-12").igst == Decimal("18000.00")

    def test_the_closed_return_reads_the_same_before_and_after_paying(self):
        unpaid = purchase(invoice_date=self.LAPSED)
        paid_later = purchase(invoice_date=self.LAPSED, paid_at=date(2026, 1, 20))

        at_the_time = itc_service.rule_37([unpaid], as_of=self.PERIOD_CLOSE)
        regenerated = itc_service.rule_37([paid_later], as_of=self.PERIOD_CLOSE)

        assert (
            regenerated.reversal_in("2025-12").total
            == at_the_time.reversal_in("2025-12").total
        )

    def test_a_payment_on_the_day_itself_does_stop_the_clock(self):
        """The boundary is inclusive: paid on the date asked about is paid."""
        invoice = purchase(invoice_date=self.LAPSED, paid_at=self.PERIOD_CLOSE)

        result = itc_service.rule_37([invoice], as_of=self.PERIOD_CLOSE)

        assert result.overdue == []
        assert result.reversal.total == Decimal("0.00")

    def test_a_payment_before_the_clock_expired_still_prevents_the_reversal(self):
        """Paying inside the 180 days is what the rule is asking for."""
        invoice = purchase(invoice_date=self.LAPSED, paid_at=date(2025, 8, 1))

        result = itc_service.rule_37([invoice], as_of=self.PERIOD_CLOSE)

        assert result.overdue == []
        assert result.approaching == []

    def test_the_later_period_that_re_avails_it_sees_the_payment(self):
        """By March the payment has happened, so nothing is standing."""
        invoice = purchase(invoice_date=self.LAPSED, paid_at=date(2026, 1, 20))

        result = itc_service.rule_37([invoice], as_of=date(2026, 3, 31))

        assert result.overdue == []
        assert result.reversal.total == Decimal("0.00")


def test_rule_37_ignores_invoices_that_never_claimed_credit():
    """Blocked credit and reverse charge have no credit to reverse."""
    blocked = purchase(id=1, invoice_date=date(2026, 1, 1), itc_eligible=False)
    rcm = purchase(id=2, invoice_date=date(2026, 1, 1), reverse_charge=True)

    result = itc_service.rule_37([blocked, rcm], as_of=date(2026, 12, 1))

    assert result.overdue == []


def test_rule_37_skips_a_purchase_carrying_no_tax():
    """A nil-rated or exempt purchase has no credit for 180 days to reverse.

    `itc_eligible` is about whether the law allows the credit; this is about
    whether there is any. An exempt supply is eligible and unpaid and can sit
    past day 180 like any other, so it reaches the tax check — and reporting a
    zero-rupee reversal on it sends a business chasing a payment for no tax
    reason, on a list whose whole purpose is naming the suppliers worth paying
    before the credit lapses.
    """
    exempt = purchase(
        invoice_date=date(2026, 1, 1),
        igst=Decimal("0.00"),
        total_value=Decimal("100000.00"),
    )

    result = itc_service.rule_37([exempt], as_of=date(2026, 12, 1))

    assert result.overdue == []
    assert result.approaching == []
    assert result.reversal.total == Decimal("0.00")


def test_rule_37_skips_an_invoice_with_no_date():
    """A missing date means extraction failed, not that 180 days have passed."""
    result = itc_service.rule_37(
        [purchase(invoice_date=None)], as_of=date(2026, 12, 1)
    )

    assert result.overdue == []
    assert result.approaching == []


def test_rule_37_counts_the_180_days_in_the_indian_calendar(monkeypatch):
    """The default "today" is the Indian date, not the UTC one.

    The invoice date is an Indian calendar date and the Act is enforced in that
    calendar. For the five and a half hours after midnight IST the UTC clock
    still reads yesterday, so an invoice that has just crossed day 180 would be
    reported as inside the window — and the reversal that GSTR-3B carries would
    be understated by the tax on it, which is credit over-claimed with interest
    running on it.
    """
    # 00:30 IST on 2 July 2026, which is still 1 July in UTC.
    just_after_midnight_ist = datetime(2026, 7, 2, 0, 30, tzinfo=gst_calendar.IST)
    monkeypatch.setattr(
        itc_service.gst_calendar,
        "today_ist",
        lambda: gst_calendar.ist_date(just_after_midnight_ist),
    )

    # Day 181 in India; day 180 if the clock is read in UTC.
    invoice = purchase(invoice_date=date(2026, 1, 2))
    result = itc_service.rule_37([invoice])

    assert [item.invoice_id for item in result.overdue] == [1]
    assert result.overdue[0].days_outstanding == 181
    assert result.reversal.igst == Decimal("18000.00")
    # The UTC reading of the same instant is the day the reversal is missed on.
    assert just_after_midnight_ist.astimezone(UTC).date() == date(2026, 7, 1)


def test_rule_37_reports_the_most_overdue_first():
    old = purchase(id=1, invoice_date=date(2025, 1, 1))
    newer = purchase(id=2, invoice_date=date(2026, 1, 1))

    result = itc_service.rule_37([newer, old], as_of=date(2026, 12, 1))

    assert [item.invoice_id for item in result.overdue] == [1, 2]


def test_rule_37_lists_the_approaching_by_how_little_time_is_left():
    """The other list has an order too, and it is the opposite one.

    Overdue is worst-first by age; approaching is soonest-first by what is
    left, because the two answer different questions — "how much have I
    already lost" against "what do I have to pay this week". The register
    arrives in whatever order the invoices were entered, so an unsorted
    approaching list would put the invoice with a month of runway above the
    one due on Friday, and the screen shows the top of it.
    """
    as_of = date(2026, 6, 10)
    later = purchase(id=1, invoice_date=as_of - timedelta(days=155))  # 25 days left
    sooner = purchase(id=2, invoice_date=as_of - timedelta(days=170))  # 10 days left

    result = itc_service.rule_37([later, sooner], as_of=as_of)

    assert [item.days_remaining for item in result.approaching] == [10, 25]
    assert [item.invoice_id for item in result.approaching] == [2, 1]


def test_rule_37_warns_from_exactly_thirty_days_out_and_not_a_day_sooner():
    """The window is a promise about notice, and both its edges are load-bearing.

    A day narrow and the business is told about the invoice with less time to
    act than the screen claims to give; a day wide and the list it is asked to
    work through every morning grows by a month's invoices, which is how a
    warning stops being read. Thirty days out is in; thirty-one is not.
    """
    invoice_date = date(2026, 1, 1)
    thirty_out = itc_service.rule_37(
        [purchase(invoice_date=invoice_date)],
        as_of=invoice_date + timedelta(days=itc_service.RULE_37_DAYS - 30),
    )
    thirty_one_out = itc_service.rule_37(
        [purchase(invoice_date=invoice_date)],
        as_of=invoice_date + timedelta(days=itc_service.RULE_37_DAYS - 31),
    )

    assert [item.days_remaining for item in thirty_out.approaching] == [30]
    assert thirty_out.approaching_amount.igst == Decimal("18000.00")

    assert thirty_one_out.approaching == []
    assert thirty_one_out.approaching_amount.total == Decimal("0.00")


def test_rule_37_marks_the_day_180_invoice_as_still_in_time():
    """``overdue`` is the flag the row is rendered from, not the list it is in.

    The two are computed separately — the item carries its own boolean and the
    result then files it under ``overdue`` or ``approaching`` — so the flag can
    disagree with the list it lands in, and day 180 is where it would: the item
    sits in ``approaching`` with nothing reversed while a row rendered from a
    wrong flag tells the business the credit is already gone.
    """
    invoice_date = date(2026, 1, 1)
    lapse = itc_service.lapse_date(invoice_date)

    in_time = itc_service.rule_37(
        [purchase(invoice_date=invoice_date)], as_of=lapse - timedelta(days=1)
    )
    gone = itc_service.rule_37([purchase(invoice_date=invoice_date)], as_of=lapse)

    (still_in_time,) = in_time.approaching
    assert still_in_time.days_remaining == 0
    assert still_in_time.overdue is False
    assert in_time.reversal.total == Decimal("0.00")

    (reversed_item,) = gone.overdue
    assert reversed_item.days_remaining == -1
    assert reversed_item.overdue is True


# ---------------------------------------------------------------------------
# Rule 37's second half — the period the credit comes back in
# ---------------------------------------------------------------------------

class TestReAvailmentBelongsToExactlyOnePeriod:
    """Both edges of both conditions, asserted on the pure function.

    Every existing test reaches this through ``summary``, which fixes the
    period to a month with a payment comfortably inside it. The credit is
    given back exactly once, in one month, so a boundary off by a day either
    hands it back twice — once in each of two adjacent returns — or never.
    """

    PERIOD = "2026-04"  # 1 – 30 April 2026.
    # Lapses 31 March 2026, the day before the period opens: reversed by the
    # March return, so April is the month entitled to take it back.
    REVERSED_BEFORE = date(2025, 10, 1)
    # One day later, and it lapses on 1 April instead.
    LAPSES_ON_THE_FIRST = date(2025, 10, 2)

    def test_the_fixture_dates_straddle_the_period_opening(self):
        assert itc_service.lapse_date(self.REVERSED_BEFORE) == date(2026, 3, 31)
        assert itc_service.lapse_date(self.LAPSES_ON_THE_FIRST) == date(2026, 4, 1)

    @pytest.mark.parametrize("paid_on", [date(2026, 4, 1), date(2026, 4, 30)])
    def test_a_payment_on_either_end_of_the_period_is_re_availed_in_it(self, paid_on):
        invoice = purchase(invoice_date=self.REVERSED_BEFORE, paid_at=paid_on)

        taken_back = itc_service.rule_37_reavailment([invoice], self.PERIOD)

        assert taken_back.igst == Decimal("18000.00")

    @pytest.mark.parametrize("paid_on", [date(2026, 3, 31), date(2026, 5, 1)])
    def test_a_payment_a_day_outside_belongs_to_the_month_it_fell_in(self, paid_on):
        invoice = purchase(invoice_date=self.REVERSED_BEFORE, paid_at=paid_on)

        assert itc_service.rule_37_reavailment([invoice], self.PERIOD).total == Decimal(
            "0.00"
        )

    def test_an_invoice_lapsing_on_the_first_of_the_period_was_never_reversed(self):
        """So there is nothing for this period to give back.

        ``rule_37`` reads ``paid_at`` as of the close of the period: an invoice
        that crossed 180 days on 1 April and was paid on the 15th was already
        excluded when April's reversal was computed, and never left the books.
        Re-availing it would credit the business twice for one invoice.
        """
        never_reversed = purchase(
            invoice_date=self.LAPSES_ON_THE_FIRST, paid_at=date(2026, 4, 15)
        )
        reversed_in_march = purchase(
            invoice_date=self.REVERSED_BEFORE, paid_at=date(2026, 4, 15)
        )

        assert itc_service.rule_37_reavailment(
            [never_reversed], self.PERIOD
        ).total == Decimal("0.00")
        assert itc_service.rule_37_reavailment(
            [reversed_in_march], self.PERIOD
        ).igst == Decimal("18000.00")


# ---------------------------------------------------------------------------
# Rules 42 and 43 — proportionate reversal
# ---------------------------------------------------------------------------

def test_rule_42_reverses_the_exempt_share_of_common_credit():
    """D1 = (E / F) x C2 — a quarter of turnover exempt reverses a quarter."""
    result = itc_service.proportionate_reversal(
        common_credit=heads(igst="40000"),
        capital_credit=heads(),
        exempt_turnover=Decimal("250000"),
        total_turnover=Decimal("1000000"),
    )

    assert result.exempt_ratio == Decimal("0.25")
    assert result.rule_42_reversal.igst == Decimal("10000.00")


def test_rule_43_spreads_capital_credit_over_sixty_months():
    """Only Tc/60 belongs to this month, and only the exempt share of it reverses."""
    result = itc_service.proportionate_reversal(
        common_credit=heads(),
        capital_credit=heads(igst="60000"),
        exempt_turnover=Decimal("500000"),
        total_turnover=Decimal("1000000"),
    )

    assert result.capital_credit_this_month.igst == Decimal("1000.00")
    assert result.rule_43_reversal.igst == Decimal("500.00")


def test_no_exempt_turnover_reverses_nothing():
    result = itc_service.proportionate_reversal(
        common_credit=heads(igst="40000"),
        capital_credit=heads(igst="60000"),
        exempt_turnover=Decimal("0"),
        total_turnover=Decimal("1000000"),
    )

    assert result.exempt_ratio == Decimal("0")
    assert result.total_reversal.total == Decimal("0.00")


def test_zero_turnover_does_not_divide_by_zero():
    """A period with no outward supply has no exempt proportion to compute."""
    result = itc_service.proportionate_reversal(
        common_credit=heads(igst="40000"),
        capital_credit=heads(),
        exempt_turnover=Decimal("0"),
        total_turnover=Decimal("0"),
    )

    assert result.exempt_ratio == Decimal("0")
    assert result.rule_42_reversal.total == Decimal("0.00")


def test_exempt_turnover_above_total_is_capped_at_everything():
    """Contradictory inputs must not reverse more credit than exists."""
    result = itc_service.proportionate_reversal(
        common_credit=heads(igst="40000"),
        capital_credit=heads(),
        exempt_turnover=Decimal("2000000"),
        total_turnover=Decimal("1000000"),
    )

    assert result.exempt_ratio == Decimal("1")
    assert result.rule_42_reversal.igst == Decimal("40000.00")


def test_reversal_splits_across_every_head():
    result = itc_service.proportionate_reversal(
        common_credit=heads(igst="1000", cgst="500", sgst="500", cess="100"),
        capital_credit=heads(),
        exempt_turnover=Decimal("500000"),
        total_turnover=Decimal("1000000"),
    )

    assert result.rule_42_reversal.igst == Decimal("500.00")
    assert result.rule_42_reversal.cgst == Decimal("250.00")
    assert result.rule_42_reversal.sgst == Decimal("250.00")
    assert result.rule_42_reversal.cess == Decimal("50.00")


# ---------------------------------------------------------------------------
# The period summary
# ---------------------------------------------------------------------------

def test_summary_pools_credit_by_head(db_session, business):
    save(db_session, business.id, invoice_number="A-1")
    save(
        db_session,
        business.id,
        invoice_number="A-2",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
    )

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.available.igst == Decimal("18000.00")
    assert summary.available.cgst == Decimal("9000.00")
    assert summary.available.sgst == Decimal("9000.00")
    assert summary.invoice_count == 2
    assert summary.reconciled is False


def test_summary_excludes_blocked_and_reverse_charge_credit(db_session, business):
    save(db_session, business.id, invoice_number="A-1")
    save(db_session, business.id, invoice_number="A-2", itc_eligible=False)
    save(db_session, business.id, invoice_number="A-3", reverse_charge=True)

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.available.igst == Decimal("18000.00")
    # Only the blocked one is unclaimed. The reverse-charge purchase is out of
    # this pool because no supplier charged its tax, not because the credit is
    # lost: it comes back at 4(A)(3) and is counted below.
    assert summary.unclaimed_count == 1
    assert summary.reverse_charge.credit.igst == Decimal("18000.00")


def test_capital_goods_credit_is_not_pooled_with_inputs(db_session, business):
    """Its credit belongs to Rule 43's sixty months, not to this month."""
    save(db_session, business.id, invoice_number="A-1", is_capital_good=True)

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.available.igst == Decimal("0.00")
    assert summary.proportionate.capital_credit.igst == Decimal("18000.00")
    assert summary.proportionate.capital_credit_this_month.igst == Decimal("300.00")


class TestReverseChargeIsALiabilityCreditCannotSettle:
    """s.9(3)/9(4): the one place a purchase creates tax to pay.

    The buyer pays the government directly, declares it in GSTR-3B at 3.1(d),
    and claims it straight back at 4(A)(3). Two halves that have to move
    together: the liability is cash whatever the credit ledger holds, because
    s.49(4) only lets credit settle "output tax" and s.2(82) puts reverse
    charge outside that definition.
    """

    def test_a_reverse_charge_purchase_carries_a_liability_and_its_credit(
        self, db_session, business
    ):
        save(db_session, business.id, invoice_number="RCM-1", reverse_charge=True)

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.reverse_charge.invoice_count == 1
        assert summary.reverse_charge.taxable_value == Decimal("100000.00")
        assert summary.reverse_charge.tax.igst == Decimal("18000.00")
        assert summary.reverse_charge.credit.igst == Decimal("18000.00")
        # And it is not in the pool the supplier's own filing evidences.
        assert summary.available.igst == Decimal("0.00")

    def test_the_credit_it_earns_is_claimable_this_period(self, db_session, business):
        save(db_session, business.id, invoice_number="RCM-1", reverse_charge=True)

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.net_available.igst == Decimal("18000.00")

    def test_credit_does_not_settle_it(self, db_session, business):
        """A ledger deep enough to clear the output tax still leaves this to pay."""
        save(db_session, business.id, invoice_number="RCM-1", reverse_charge=True)
        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-1",
                invoice_date=date(2026, 4, 20),
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            )
        )
        db_session.commit()

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        # The reverse-charge credit settled the whole output tax...
        assert summary.set_off.total_cash == Decimal("0.00")
        # ...and the reverse-charge tax itself is still cash out of the door.
        assert summary.cash_payable == Decimal("18000.00")

    def test_a_blocked_reverse_charge_purchase_pays_and_gets_nothing_back(
        self, db_session, business
    ):
        """s.17(5) on top of 9(3): the most expensive row on the register."""
        save(
            db_session,
            business.id,
            invoice_number="RCM-1",
            reverse_charge=True,
            itc_eligible=False,
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.reverse_charge.tax.igst == Decimal("18000.00")
        assert summary.reverse_charge.credit.igst == Decimal("0.00")
        assert summary.cash_payable == Decimal("18000.00")
        assert summary.unclaimed_count == 1

    def test_a_row_carrying_no_tax_is_not_a_liability(self, db_session, business):
        """Empty tax boxes are an extraction that missed them, not a supply."""
        save(
            db_session,
            business.id,
            invoice_number="RCM-1",
            reverse_charge=True,
            igst=Decimal("0.00"),
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.reverse_charge.invoice_count == 0
        assert summary.cash_payable == Decimal("0.00")

    def test_the_reconciliation_cap_leaves_it_alone(self, db_session, business):
        """GSTR-2B has nothing to say about tax the buyer pays themselves.

        The cap scales the pool a supplier's filing evidences. A 2B that shows
        nothing scales that pool to nothing — and used to be read as evidence
        against a reverse-charge credit no supplier was ever going to declare.
        """
        save(db_session, business.id, invoice_number="RCM-1", reverse_charge=True)
        reconciliation.store_gstr2b(db_session, business.id, PERIOD, [])
        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.reconciled is True
        assert summary.reverse_charge.credit.igst == Decimal("18000.00")
        assert summary.net_available.igst == Decimal("18000.00")


class TestCapitalCreditIsDueForSixtyMonths:
    """Rule 43 gives a capital good sixty instalments, not one.

    ``summarise`` pooled capital credit from the period's own purchases, so a
    machine bought in April got a sixtieth of its credit in April and nothing
    in May — fifty-nine sixtieths of the credit, 98% of it, was simply never
    claimed. ``filing`` puts ``capital_credit_this_month`` into table 4(A)(5)
    of GSTR-3B, so the loss went into the filed return and the business paid
    the difference in cash.
    """

    def _capital_good(self, db, business, **kwargs):
        return save(
            db,
            business.id,
            invoice_number=kwargs.pop("invoice_number", "CAP-1"),
            is_capital_good=True,
            igst=Decimal("60000.00"),
            **kwargs,
        )

    def test_the_instalment_keeps_coming_in_later_months(self, db_session, business):
        self._capital_good(
            db_session, business, invoice_date=date(2026, 4, 15), period="2026-04"
        )

        for period in ("2026-04", "2026-05", "2027-04", "2031-03"):
            summary = itc_service.summarise(db_session, business.id, period)
            assert summary.proportionate.capital_credit_this_month.igst == Decimal(
                "1000.00"
            ), period

    def test_the_sixtieth_month_is_the_last_one(self, db_session, business):
        # Bought April 2026: April 2026 is instalment 1, March 2031 is
        # instalment 60, and April 2031 is past the end of the schedule.
        self._capital_good(
            db_session, business, invoice_date=date(2026, 4, 15), period="2026-04"
        )

        last = itc_service.summarise(db_session, business.id, "2031-03")
        after = itc_service.summarise(db_session, business.id, "2031-04")

        assert last.proportionate.capital_credit_this_month.igst == Decimal("1000.00")
        assert after.proportionate.capital_credit.igst == Decimal("0.00")
        assert after.proportionate.capital_credit_this_month.igst == Decimal("0.00")

    def test_the_sixty_instalments_add_up_to_the_whole_credit(self, db_session, business):
        self._capital_good(
            db_session, business, invoice_date=date(2026, 4, 15), period="2026-04"
        )

        claimed = sum(
            (
                itc_service.summarise(
                    db_session, business.id, gst_calendar.months_before("2031-03", back)
                ).proportionate.capital_credit_this_month.igst
                for back in range(60)
            ),
            Decimal("0.00"),
        )

        assert claimed == Decimal("60000.00")

    def test_goods_still_in_service_pool_together(self, db_session, business):
        """Each contributes its own sixtieth, so the month's instalment is both."""
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-OLD",
            invoice_date=date(2024, 7, 3),
            period="2024-07",
        )
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-NEW",
            invoice_date=date(2026, 4, 15),
            period="2026-04",
        )

        summary = itc_service.summarise(db_session, business.id, "2026-04")

        assert summary.proportionate.capital_credit.igst == Decimal("120000.00")
        assert summary.proportionate.capital_credit_this_month.igst == Decimal("2000.00")

    def test_a_good_that_has_run_out_drops_out_of_the_pool(self, db_session, business):
        """Sixty months on, only the one still in service is left."""
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-EXPIRED",
            invoice_date=date(2021, 4, 5),
            period="2021-04",
        )
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-LIVE",
            invoice_date=date(2026, 4, 15),
            period="2026-04",
        )

        summary = itc_service.summarise(db_session, business.id, "2026-04")

        assert summary.proportionate.capital_credit.igst == Decimal("60000.00")
        assert summary.proportionate.capital_credit_this_month.igst == Decimal("1000.00")

    def test_a_purchase_the_period_predates_is_not_claimed(self, db_session, business):
        """Re-opening March must not claim credit on April's machine."""
        self._capital_good(
            db_session, business, invoice_date=date(2026, 4, 15), period="2026-04"
        )

        summary = itc_service.summarise(db_session, business.id, "2026-03")

        assert summary.proportionate.capital_credit_this_month.igst == Decimal("0.00")

    def test_a_blocked_capital_good_has_no_credit_to_spread(self, db_session, business):
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-BLOCKED",
            invoice_date=date(2026, 4, 15),
            period="2026-04",
            itc_eligible=False,
        )
        self._capital_good(
            db_session,
            business,
            invoice_number="CAP-RCM",
            invoice_date=date(2026, 4, 15),
            period="2026-04",
            reverse_charge=True,
        )

        summary = itc_service.summarise(db_session, business.id, "2026-04")

        assert summary.proportionate.capital_credit.igst == Decimal("0.00")

    def test_a_capital_good_with_no_period_is_not_placed_on_the_schedule(
        self, db_session, business
    ):
        """A date that was never extracted cannot anchor sixty months."""
        self._capital_good(
            db_session, business, invoice_date=None, period=None, status=InvoiceStatus.PARSED
        )

        summary = itc_service.summarise(db_session, business.id, "2026-04")

        assert summary.proportionate.capital_credit.igst == Decimal("0.00")

    def test_the_instalment_reaches_the_return(self, db_session, business):
        """``filing`` reads it into table 4(A)(5), which is where the loss landed."""
        self._capital_good(
            db_session, business, invoice_date=date(2026, 4, 15), period="2026-04"
        )

        may = filing.build_gstr3b(db_session, business, "2026-05")

        assert may["itc_elg"]["itc_avl"][0]["iamt"] == 1000.00
        assert may["itc_elg"]["itc_net"]["iamt"] == 1000.00


def test_summary_caps_credit_at_what_reconciliation_found_eligible(db_session, business):
    """Only GSTR-2B establishes what a supplier actually declared."""
    save(db_session, business.id, invoice_number="A-1")
    save(db_session, business.id, invoice_number="A-2")
    # Only one of the two was declared by the supplier.
    reconciliation.store_gstr2b(
        db_session,
        business.id,
        PERIOD,
        [
            GSTR2BRecord(
                supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
                invoice_number="A-1",
                invoice_date=date(2026, 4, 15),
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            )
        ],
    )
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.reconciled is True
    assert summary.available.igst == Decimal("18000.00")  # Not 36,000.
    assert summary.itc_at_risk == Decimal("18000.00")


def test_a_failed_run_does_not_cap_the_period_s_credit_at_nothing(db_session, business):
    """The zeros on an unfinished run are column defaults, not a 2B's verdict.

    A run that fails is recorded rather than swallowed, so it becomes the newest
    row for the period with ``itc_eligible`` still at 0.00. Read as the current
    position, that scaled the whole pool to nought and reported ``reconciled``:
    the GSTR-3B built from it fills table 4(A) with zeros and pays the entire
    output tax in cash, while the credit sits unclaimed.
    """
    save(db_session, business.id, invoice_number="A-1")
    save(db_session, business.id, invoice_number="A-2")
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.FAILED,
            error="the 2B row was unreadable",
        )
    )
    db_session.commit()

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.available.igst == Decimal("36000.00")
    assert summary.reconciled is False


def test_a_failed_re_run_leaves_the_last_completed_cap_standing(db_session, business):
    """Periods are reconciled repeatedly, and the later attempt can fail.

    The completed run's cap is still the best evidence about what suppliers
    declared. Falling back to the books instead would *raise* the claim above
    what the 2B supports, which is the overstatement that draws a notice.
    """
    save(db_session, business.id, invoice_number="A-1")
    save(db_session, business.id, invoice_number="A-2")
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.COMPLETED,
            itc_eligible=Decimal("18000.00"),
            itc_at_risk=Decimal("18000.00"),
        )
    )
    db_session.commit()
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.FAILED,
            error="boom",
        )
    )
    db_session.commit()

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.reconciled is True
    assert summary.available.igst == Decimal("18000.00")
    assert summary.itc_at_risk == Decimal("18000.00")


def test_the_3b_it_builds_still_claims_the_credit_after_a_failed_run(db_session, business):
    """The figure that actually costs money: table 4(A) of GSTR-3B."""
    save(db_session, business.id, invoice_number="A-1")
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.FAILED,
            error="boom",
        )
    )
    db_session.commit()

    document = filing.build_gstr3b(db_session, business, PERIOD)

    assert document["itc_elg"]["itc_avl"][0]["iamt"] == 18000.00
    assert document["itc_elg"]["itc_net"]["iamt"] == 18000.00


def test_summary_looks_beyond_the_period_for_rule_37(db_session, business):
    """The invoice that crosses 180 days is one from months ago."""
    save(
        db_session,
        business.id,
        invoice_number="OLD-1",
        invoice_date=date(2025, 6, 1),
        period="2025-06",
    )

    summary = itc_service.summarise(
        db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
    )

    assert summary.invoice_count == 0  # Nothing booked in the period itself.
    assert len(summary.rule_37.overdue) == 1
    assert summary.rule_37.reversal.igst == Decimal("18000.00")


class TestRule37IsPaidOnceNotEveryMonthAfter:
    """The reversal belongs to the month the 180 days ran out.

    Rule 37 is paid in the return for the tax period in which the clock
    expires, and re-availed when the supplier is finally paid. It is not a
    balance that is re-declared every month.

    ``rule_37.reversal`` is the standing exposure over the whole register,
    which is what the screen's list of overdue invoices is for. Charging that
    to every period's credit reversed the same invoice again in every return
    that followed it, and each of those returns still reproduced itself
    exactly — which is what kept it out of sight.
    """

    # 181 days after 31 October 2025 is 30 April 2026, so this purchase lapses
    # on the last day of PERIOD and in no other month.
    LAPSES_IN_PERIOD = date(2025, 10, 31)

    def lapsed_purchase(self, db, business):
        return save(
            db,
            business.id,
            invoice_number="OLD-1",
            invoice_date=self.LAPSES_IN_PERIOD,
            period="2025-10",
        )

    def test_the_period_it_lapsed_in_reverses_it(self, db_session, business):
        self.lapsed_purchase(db_session, business)

        summary = itc_service.summarise(
            db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
        )

        assert summary.rule_37_reversal.igst == Decimal("18000.00")
        assert summary.total_reversal.igst == Decimal("18000.00")

    def test_the_month_after_does_not_reverse_it_again(self, db_session, business):
        self.lapsed_purchase(db_session, business)

        summary = itc_service.summarise(
            db_session, business.id, "2026-05", as_of=date(2026, 5, 31)
        )

        # Still standing, and still listed for the screen...
        assert summary.rule_37.reversal.igst == Decimal("18000.00")
        assert len(summary.rule_37.overdue) == 1
        # ...but May's return does not give it back a second time.
        assert summary.rule_37_reversal.igst == Decimal("0.00")

    def test_it_is_not_reversed_a_year_of_returns_later(self, db_session, business):
        self.lapsed_purchase(db_session, business)

        for period, end in (
            ("2026-06", date(2026, 6, 30)),
            ("2026-09", date(2026, 9, 30)),
            ("2027-03", date(2027, 3, 31)),
        ):
            summary = itc_service.summarise(
                db_session, business.id, period, as_of=end
            )
            assert summary.rule_37_reversal.total == Decimal("0.00"), period

    def test_the_month_before_it_lapsed_reverses_nothing(self, db_session, business):
        self.lapsed_purchase(db_session, business)

        summary = itc_service.summarise(
            db_session, business.id, "2026-03", as_of=date(2026, 3, 31)
        )

        assert summary.rule_37_reversal.total == Decimal("0.00")
        assert summary.rule_37.reversal.total == Decimal("0.00")

    def test_the_period_s_own_credit_survives_a_later_month(self, db_session, business):
        """What the double reversal actually cost.

        May has ₹18,000 of its own input credit and one lapsed invoice from
        October. Charged the standing exposure, May's net credit came out at
        zero and the business paid the whole month's output tax in cash.
        """
        self.lapsed_purchase(db_session, business)
        save(
            db_session,
            business.id,
            invoice_number="MAY-1",
            invoice_date=date(2026, 5, 10),
            period="2026-05",
        )

        summary = itc_service.summarise(
            db_session, business.id, "2026-05", as_of=date(2026, 5, 31)
        )

        assert summary.available.igst == Decimal("18000.00")
        assert summary.net_available.igst == Decimal("18000.00")

    def test_a_purchase_still_inside_its_180_days_reverses_nowhere(
        self, db_session, business
    ):
        save(
            db_session,
            business.id,
            invoice_number="RECENT-1",
            invoice_date=date(2026, 4, 1),
            period=PERIOD,
        )

        summary = itc_service.summarise(
            db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
        )

        assert summary.rule_37_reversal.total == Decimal("0.00")

    def test_a_paid_invoice_lapses_in_no_period_at_all(self, db_session, business):
        """Paying the supplier stops the clock, wherever it had got to."""
        save(
            db_session,
            business.id,
            invoice_number="OLD-PAID",
            invoice_date=self.LAPSES_IN_PERIOD,
            period="2025-10",
            paid_at=datetime(2026, 2, 1, tzinfo=UTC),
        )

        summary = itc_service.summarise(
            db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
        )

        assert summary.rule_37_reversal.total == Decimal("0.00")

    def test_the_whole_of_day_180_is_still_allowed(self, db_session, business):
        """Day 180 falls in April, day 181 in May: the reversal is May's."""
        save(
            db_session,
            business.id,
            # 180 days after this is 2026-04-30; the 181st is 2026-05-01.
            invoice_date=date(2025, 11, 1),
            period="2025-11",
            invoice_number="EDGE-1",
        )

        april = itc_service.summarise(
            db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
        )
        may = itc_service.summarise(
            db_session, business.id, "2026-05", as_of=date(2026, 5, 31)
        )

        assert april.rule_37_reversal.total == Decimal("0.00")
        assert may.rule_37_reversal.igst == Decimal("18000.00")

    def test_an_overdue_item_with_no_invoice_date_is_skipped_not_raised_on(self):
        """``reversal_in`` re-derives the lapse date from the item it is given.

        :func:`~app.services.itc.rule_37` drops a dateless invoice before it
        can become an item, so nothing in the product builds this today. The
        field is still ``date | None`` — ``Rule37Item`` declares it that way,
        and ``as_dict`` serialises the None case — so the method has to hold
        for a result it did not build itself.

        Without the guard it is not a wrong figure, it is a ``TypeError``
        inside ``lapse_date``, on the path that produces GSTR-3B's reversal
        line. Skipping is the same answer ``rule_37`` already gives: a missing
        date means the extraction failed, not that 180 days have passed, and
        there is no honest lapse month to charge it to.
        """
        dateless = itc_service.Rule37Item(
            invoice_id=1,
            invoice_number="NO-DATE-1",
            supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
            supplier_name="Northwind Supplies",
            invoice_date=None,
            days_outstanding=None,
            days_remaining=None,
            tax=heads(igst="18000"),
            overdue=True,
        )
        dated = itc_service.Rule37Item(
            invoice_id=2,
            invoice_number="DATED-1",
            supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
            supplier_name="Northwind Supplies",
            # 181 days later is 2026-04-30, so this one does belong to PERIOD.
            invoice_date=date(2025, 10, 31),
            days_outstanding=181,
            days_remaining=-1,
            tax=heads(igst="5000"),
            overdue=True,
        )
        result = itc_service.Rule37Result(
            overdue=[dateless, dated],
            reversal=heads(igst="23000"),
        )

        # The dated one still lands, so this is the guard skipping one item
        # rather than the method bailing out on the first.
        assert result.reversal_in(PERIOD).igst == Decimal("5000.00")
        # And the dateless credit is not quietly charged to some other month.
        assert result.reversal_in("2026-05").total == Decimal("0.00")


class TestRule37GivesTheCreditBackWhenTheSupplierIsPaid:
    """The other half of Rule 37, and the half that did not exist.

    The proviso to s.16(2)(d) is not a forfeiture clause: "the recipient shall
    be entitled to avail of the input tax credit on payment made by him". The
    reversal is a deposit, and paying the supplier redeems it in the return for
    the period the payment falls in.

    Only the reversal was implemented. Setting ``paid_at`` stopped
    :func:`~app.services.itc.rule_37` reporting the invoice at all, which
    stopped the reversal recurring and returned nothing — so every invoice that
    ever crossed 180 days cost its whole ITC, once, permanently. For a business
    that pays anything late, that is a standing overstatement of tax.
    """

    # 181 days after 31 October 2025 is 30 April 2026, so this purchase lapses
    # in 2026-04 and its credit is given back in that month's return.
    LAPSED = date(2025, 10, 31)
    LAPSE_PERIOD = "2026-04"

    def lapsed_and_paid(self, db, business, paid_at, **kwargs):
        return save(
            db,
            business.id,
            invoice_number=kwargs.pop("invoice_number", "OLD-1"),
            invoice_date=self.LAPSED,
            period="2025-10",
            paid_at=paid_at,
            **kwargs,
        )

    def test_the_period_the_supplier_is_paid_in_takes_it_back(
        self, db_session, business
    ):
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        summary = itc_service.summarise(
            db_session, business.id, "2026-09", as_of=date(2026, 9, 30)
        )

        assert summary.rule_37_reavailment.igst == Decimal("18000.00")
        # And it reaches the credit that settles the liability, which is the
        # only reason the figure is worth computing.
        assert summary.net_available.igst == Decimal("18000.00")

    def test_it_is_taken_back_exactly_once(self, db_session, business):
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        for period, end in (
            ("2026-10", date(2026, 10, 31)),
            ("2026-11", date(2026, 11, 30)),
            ("2027-02", date(2027, 2, 28)),
        ):
            summary = itc_service.summarise(db_session, business.id, period, as_of=end)
            assert summary.rule_37_reavailment.total == Decimal("0.00"), period

    def test_the_months_before_the_payment_take_back_nothing(
        self, db_session, business
    ):
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        summary = itc_service.summarise(
            db_session, business.id, "2026-08", as_of=date(2026, 8, 31)
        )

        assert summary.rule_37_reavailment.total == Decimal("0.00")

    def test_the_reversal_and_the_re_availment_are_the_same_amount(
        self, db_session, business
    ):
        """What the round trip has to come to, over the two returns it spans."""
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        reversed_in_april = itc_service.summarise(
            db_session, business.id, self.LAPSE_PERIOD, as_of=date(2026, 4, 30)
        ).rule_37_reversal
        back_in_september = itc_service.summarise(
            db_session, business.id, "2026-09", as_of=date(2026, 9, 30)
        ).rule_37_reavailment

        assert reversed_in_april.total == back_in_september.total == Decimal("18000.00")

    def test_paying_inside_the_month_it_lapsed_gives_back_nothing(
        self, db_session, business
    ):
        """The case that would invent credit out of nothing.

        ``rule_37`` reads ``paid_at`` as of the close of the period, so an
        invoice that crossed 180 days on the 15th and was paid on the 20th of
        the same month was never reversed by any return. Re-availing it would
        hand back credit the business never gave up — the one direction of this
        rule that costs the government rather than the taxpayer.
        """
        self.lapsed_and_paid(db_session, business, date(2026, 4, 20))

        summary = itc_service.summarise(
            db_session, business.id, self.LAPSE_PERIOD, as_of=date(2026, 4, 30)
        )

        assert summary.rule_37_reversal.total == Decimal("0.00")
        assert summary.rule_37_reavailment.total == Decimal("0.00")

    def test_an_invoice_paid_before_it_ever_lapsed_gives_back_nothing(
        self, db_session, business
    ):
        self.lapsed_and_paid(db_session, business, date(2026, 1, 10))

        summary = itc_service.summarise(
            db_session, business.id, "2026-01", as_of=date(2026, 1, 31)
        )

        assert summary.rule_37_reavailment.total == Decimal("0.00")

    def test_a_purchase_that_never_carried_credit_gives_back_nothing(
        self, db_session, business
    ):
        """Blocked under s.17(5), or reverse charge: there was no credit to reverse."""
        self.lapsed_and_paid(
            db_session,
            business,
            date(2026, 9, 15),
            invoice_number="BLOCKED-1",
            itc_eligible=False,
        )
        self.lapsed_and_paid(
            db_session,
            business,
            date(2026, 9, 15),
            invoice_number="RCM-1",
            reverse_charge=True,
        )

        summary = itc_service.summarise(
            db_session, business.id, "2026-09", as_of=date(2026, 9, 30)
        )

        assert summary.rule_37_reavailment.total == Decimal("0.00")

    def test_an_exempt_purchase_carrying_no_tax_gives_back_nothing(
        self, db_session, business
    ):
        """Credit-eligible on paper, nil in fact.

        A nil-rated or exempt purchase — unbranded foodgrain, a farm supply —
        is an ordinary purchase invoice with ``itc_eligible`` left on and every
        tax head at zero, because nothing was charged. It passes both of the
        rule's real conditions: paid this month, lapsed months ago.

        Nothing was ever reversed on it, so nothing can come back. The arithmetic
        happens to agree — adding a zero ``TaxHeads`` changes no total — but the
        invoice does not belong in this calculation at all, and letting it through
        would put a row with no tax on it into the 4(A)(5) working a reviewer
        reads to justify the figure.
        """
        self.lapsed_and_paid(
            db_session,
            business,
            date(2026, 9, 15),
            invoice_number="EXEMPT-1",
            igst=Decimal("0.00"),
            cgst=Decimal("0.00"),
            sgst=Decimal("0.00"),
            cess=Decimal("0.00"),
            total_value=Decimal("100000.00"),
        )
        # A real credit alongside it, so a reavailment of zero cannot be the
        # whole function silently returning nothing.
        self.lapsed_and_paid(
            db_session, business, date(2026, 9, 15), invoice_number="TAXED-1"
        )

        summary = itc_service.summarise(
            db_session, business.id, "2026-09", as_of=date(2026, 9, 30)
        )

        assert summary.rule_37_reavailment.total == Decimal("18000.00")

    def test_it_is_claimed_in_table_4a_of_the_3b(self, db_session, business):
        """Where the portal expects it, and where the netting has to tie.

        4(A) is credit available and 4(C) is 4(A) less 4(B). A re-availment
        that reached ``net_available`` but not the ``itc_avl`` row would file a
        return whose own three lines do not add up.
        """
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        document = filing.build_gstr3b(db_session, business, "2026-09")

        other_itc = document["itc_elg"]["itc_avl"][0]
        assert other_itc["ty"] == "OTH"
        assert other_itc["iamt"] == 18000.0
        assert document["itc_elg"]["itc_net"]["iamt"] == 18000.0

    def test_the_re_availment_is_not_common_credit_for_rule_42(
        self, db_session, business
    ):
        """It already bore the exempt ratio when it was first availed.

        Rule 42 apportions the credit of the period that *takes* it. Credit
        being restored was apportioned in its own period, and running it
        through the ratio a second time would reverse the exempt share twice.
        """
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        summary = itc_service.summarise(
            db_session,
            business.id,
            "2026-09",
            as_of=date(2026, 9, 30),
            exempt_turnover=Decimal("50000.00"),
            total_turnover=Decimal("100000.00"),
        )

        assert summary.proportionate.common_credit.total == Decimal("0.00")
        assert summary.rule_37_reavailment.igst == Decimal("18000.00")
        assert summary.net_available.igst == Decimal("18000.00")

    def test_the_endpoint_reports_it(self, auth_client, db_session, business):
        self.lapsed_and_paid(db_session, business, date(2026, 9, 15))

        body = auth_client.get("/api/v1/itc?period=2026-09").json()

        assert body["rule_37_reavailment"]["igst"] == "18000.00"


def test_net_available_never_goes_negative(db_session, business):
    """A reversal larger than the period's credit is a liability, not negative credit.

    Dated so the 181st day is 30 April. It was 1 June 2025, which lapses in
    *November* — so April's reversal was zero and this asserted 0 == 0 over an
    empty formula, passing whichever way the reversal was signed. The floor it
    is named for was never reached.
    """
    save(
        db_session,
        business.id,
        invoice_number="OLD-1",
        invoice_date=date(2025, 10, 31),
        period="2025-10",
    )

    summary = itc_service.summarise(
        db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
    )

    # There is something to floor: ₹18,000 reversed against no credit at all.
    assert summary.rule_37_reversal.igst == Decimal("18000.00")
    assert summary.available.igst == Decimal("0.00")

    assert summary.net_available.igst == Decimal("0.00")
    assert summary.net_available.total == Decimal("0.00")


def test_net_available_combines_every_term_in_the_same_period(db_session, business):
    """The one arrangement where each part of the formula is load-bearing.

    ``net = max(0, available + capital_credit_this_month - reversal)``, where
    the reversal is Rule 37's plus Rule 42/43's. Every other test here leaves
    at least one of those terms at zero, and a term that is zero cannot show
    whether it is added or subtracted — so the sign of each was never actually
    asserted. This also runs it on CGST/SGST/cess rather than IGST, which is
    the split an intra-state buyer actually has.

    Worked through by hand:

    ==========================  =======  =======  =====
    Term                          CGST     SGST    Cess
    ==========================  =======  =======  =====
    Credit on this period's
    inputs                       9000     9000    1000
    Capital credit 12000/60        100      100       0
    Rule 42 (25% of inputs)     -2250    -2250    -250
    Rule 43 (25% of monthly)      -25      -25       0
    Rule 37 (unpaid > 180 days)  -500     -500       0
    ==========================  =======  =======  =====
    Net available                6325     6325     750
    """
    # This period's input credit.
    save(
        db_session,
        business.id,
        invoice_number="IN-1",
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
        cess=Decimal("1000.00"),
    )
    # A capital good, whose credit belongs to Rule 43's sixty months.
    save(
        db_session,
        business.id,
        invoice_number="CAP-1",
        is_capital_good=True,
        igst=Decimal("0.00"),
        cgst=Decimal("6000.00"),
        sgst=Decimal("6000.00"),
        cess=Decimal("0.00"),
    )
    # An earlier invoice whose 180 days run out inside this period: Rule 37
    # reverses it here, and only here. Dated so the 181st day is 30 April —
    # a purchase that lapsed in some earlier month belongs to that month's
    # return, not to this one's.
    save(
        db_session,
        business.id,
        invoice_number="OLD-1",
        invoice_date=date(2025, 10, 31),
        period="2025-10",
        igst=Decimal("0.00"),
        cgst=Decimal("500.00"),
        sgst=Decimal("500.00"),
        cess=Decimal("0.00"),
    )

    summary = itc_service.summarise(
        db_session,
        business.id,
        PERIOD,
        as_of=date(2026, 4, 30),
        exempt_turnover=Decimal("25000.00"),
        total_turnover=Decimal("100000.00"),
    )

    # The inputs to the formula, so a failure below says which term moved.
    assert summary.available.cgst == Decimal("9000.00")
    assert summary.proportionate.capital_credit_this_month.cgst == Decimal("100.00")
    assert summary.proportionate.rule_42_reversal.cgst == Decimal("2250.00")
    assert summary.proportionate.rule_43_reversal.cgst == Decimal("25.00")
    assert summary.rule_37_reversal.cgst == Decimal("500.00")

    assert summary.net_available.cgst == Decimal("6325.00")
    assert summary.net_available.sgst == Decimal("6325.00")
    assert summary.net_available.cess == Decimal("750.00")
    assert summary.net_available.igst == Decimal("0.00")


def test_net_available_adds_reverse_charge_and_re_availed_credit_on_the_intra_state_split(
    db_session, business
):
    """The other two terms of the same formula, on the heads an SMB actually has.

    ``net_available`` adds four things and subtracts one, and the test above
    proves the signs of ``available``, the capital instalment and the reversal.
    The remaining two — the credit a reverse-charge purchase earns, and credit
    re-availed under the proviso to s.16(2)(d) when a supplier is finally paid
    — are asserted only on IGST, and only one at a time. Flipping either sign
    on CGST or SGST changed nothing anywhere in this suite.

    That is the split that matters for both. Reverse charge for a small
    business is freight under a GTA and an advocate's fee, which are local
    supplies carrying CGST+SGST; and the invoice paid six months late is
    usually the local supplier who was patient about it. A sign wrong here
    understates the credit by twice the reverse-charge tax — on the return of
    a business whose only reverse-charge exposure is intra-state, which is
    most of them.

    Worked through by hand:

    ==========================  =======  =======  =====
    Term                          CGST     SGST    Cess
    ==========================  =======  =======  =====
    Credit on this period's
    inputs                       9000     9000    1000
    Capital credit 6000/60        100      100      10
    Reverse charge, claimed
    back at 4(A)(3)              2000     2000     200
    Re-availed on payment         500      500      50
    ==========================  =======  =======  =====
    Net available               11600    11600    1260
    """
    # This period's input credit.
    save(
        db_session,
        business.id,
        invoice_number="IN-1",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
        cess=Decimal("1000.00"),
    )
    # A capital good: Rule 43 gives this month one of its sixty instalments.
    save(
        db_session,
        business.id,
        invoice_number="CAP-1",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        is_capital_good=True,
        igst=Decimal("0.00"),
        cgst=Decimal("6000.00"),
        sgst=Decimal("6000.00"),
        cess=Decimal("600.00"),
    )
    # Freight under a GTA: the business owes this tax itself and claims the
    # same figure straight back, so it is credit that never sat in `available`.
    save(
        db_session,
        business.id,
        invoice_number="GTA-1",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        reverse_charge=True,
        taxable_value=Decimal("22222.22"),
        igst=Decimal("0.00"),
        cgst=Decimal("2000.00"),
        sgst=Decimal("2000.00"),
        cess=Decimal("200.00"),
    )
    # Last August's invoice, reversed when its 180 days ran out in February and
    # paid this month. Dated so it had already lapsed before April began: an
    # invoice that lapses and is paid inside one period was never reversed, and
    # re-availing it would hand back credit the return never gave up.
    save(
        db_session,
        business.id,
        invoice_number="OLD-1",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        invoice_date=date(2025, 8, 1),
        period="2025-08",
        paid_at=date(2026, 4, 10),
        igst=Decimal("0.00"),
        cgst=Decimal("500.00"),
        sgst=Decimal("500.00"),
        cess=Decimal("50.00"),
    )

    summary = itc_service.summarise(
        db_session, business.id, PERIOD, as_of=date(2026, 4, 30)
    )

    # The terms, so a failure below says which one moved.
    assert summary.available.cgst == Decimal("9000.00")
    assert summary.proportionate.capital_credit_this_month.cgst == Decimal("100.00")
    assert summary.reverse_charge.credit.cgst == Decimal("2000.00")
    assert summary.rule_37_reversal.cgst == Decimal("0.00")

    assert summary.net_available.cgst == Decimal("11600.00")
    assert summary.net_available.sgst == Decimal("11600.00")
    assert summary.net_available.cess == Decimal("1260.00")
    assert summary.net_available.igst == Decimal("0.00")


def test_turnover_split_treats_untaxed_sales_as_exempt(db_session, business):
    db_session.add_all(
        [
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-1",
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            ),
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-2",
                period=PERIOD,
                taxable_value=Decimal("50000.00"),
                total_value=Decimal("50000.00"),
            ),
        ]
    )
    db_session.commit()

    _, exempt, total = itc_service._outward_tax_and_turnover(db_session, business.id, PERIOD)

    assert exempt == Decimal("50000.00")
    assert total == Decimal("150000.00")


def test_output_tax_ignores_a_sale_whose_extraction_failed(db_session, business):
    """A failed row is not in GSTR-1, so it is not output tax either.

    A re-parse of an already-parsed invoice leaves the first read's figures on
    the row and the status at FAILED. Counting them here charges the business
    for a supply the return it files does not declare.
    """
    db_session.add_all(
        [
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-1",
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            ),
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.FAILED,
                invoice_number="S-2",
                period=PERIOD,
                taxable_value=Decimal("200000.00"),
                igst=Decimal("36000.00"),
                total_value=Decimal("236000.00"),
            ),
        ]
    )
    db_session.commit()

    output, _, _ = itc_service._outward_tax_and_turnover(db_session, business.id, PERIOD)

    assert output.igst == Decimal("18000.00")


def test_output_tax_keeps_each_head_on_its_own_head(db_session, business):
    """Four sums come back positionally, and two of them are usually equal.

    CGST and SGST are half the rate each, so on a well-behaved intra-state
    invoice they are the same number and a query that swapped the two columns
    would be invisible in every other test here. They are not the same number
    when a supplier's software puts the odd paisa of an odd taxable value on
    one head — which is exactly the invoice a swap would misreport, and it
    lands in the 3B as tax declared under the wrong head of a return that is
    split between two governments.
    """
    db_session.add(
        Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=InvoiceStatus.PARSED,
            invoice_number="S-1",
            period=PERIOD,
            taxable_value=Decimal("1000.05"),
            cgst=Decimal("90.01"),
            sgst=Decimal("90.00"),
            igst=Decimal("0.00"),
            cess=Decimal("12.34"),
            total_value=Decimal("1192.40"),
        )
    )
    db_session.commit()

    output, _, _ = itc_service._outward_tax_and_turnover(db_session, business.id, PERIOD)

    assert output.igst == Decimal("0.00")
    assert output.cgst == Decimal("90.01")
    assert output.sgst == Decimal("90.00")
    assert output.cess == Decimal("12.34")


def test_turnover_split_ignores_a_sale_whose_extraction_failed(db_session, business):
    """A row with no readable tax is not evidence of an exempt supply.

    Left in, it counts as exempt turnover — which raises the Rule 42 ratio and
    reverses credit on the strength of a parse that failed.
    """
    db_session.add_all(
        [
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-1",
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            ),
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.FAILED,
                invoice_number="S-2",
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                total_value=Decimal("100000.00"),
            ),
        ]
    )
    db_session.commit()

    _, exempt, total = itc_service._outward_tax_and_turnover(db_session, business.id, PERIOD)

    assert exempt == Decimal("0.00")
    assert total == Decimal("100000.00")


def test_outward_tax_and_turnover_covers_all_dimensions(db_session, business):
    """The single scan must produce correct output tax, exempt and total turnover."""
    db_session.add_all(
        [
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-1",
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                igst=Decimal("18000.00"),
                total_value=Decimal("118000.00"),
            ),
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-2",
                period=PERIOD,
                taxable_value=Decimal("50000.00"),
                cgst=Decimal("4500.00"),
                sgst=Decimal("4500.00"),
                cess=Decimal("100.00"),
                total_value=Decimal("59100.00"),
            ),
            # Exempt supply: non-zero taxable, all tax heads zero.
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.PARSED,
                invoice_number="S-3",
                period=PERIOD,
                taxable_value=Decimal("25000.00"),
                total_value=Decimal("25000.00"),
            ),
            # Failed — should be excluded.
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                status=InvoiceStatus.FAILED,
                invoice_number="S-4",
                period=PERIOD,
                taxable_value=Decimal("999999.00"),
                igst=Decimal("180000.00"),
                total_value=Decimal("1179999.00"),
            ),
        ]
    )
    db_session.commit()

    output_tax, exempt, total = itc_service._outward_tax_and_turnover(
        db_session, business.id, PERIOD
    )

    assert output_tax.igst == Decimal("18000.00")
    assert output_tax.cgst == Decimal("4500.00")
    assert output_tax.sgst == Decimal("4500.00")
    assert output_tax.cess == Decimal("100.00")
    assert exempt == Decimal("25000.00")
    assert total == Decimal("175000.00")


def test_a_failed_sale_does_not_make_the_business_pay_cash(db_session, business):
    """The end of the chain: an inflated liability is cash out of the door."""
    save(db_session, business.id, invoice_number="A-1")  # ₹18,000 of credit.
    db_session.add(
        Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=InvoiceStatus.FAILED,
            invoice_number="S-1",
            period=PERIOD,
            taxable_value=Decimal("500000.00"),
            igst=Decimal("90000.00"),
            total_value=Decimal("590000.00"),
        )
    )
    db_session.commit()

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.output_tax.igst == Decimal("0.00")
    assert summary.set_off.cash_payable.igst == Decimal("0.00")


def test_summary_set_off_uses_the_net_credit(db_session, business):
    save(db_session, business.id, invoice_number="A-1")
    db_session.add(
        Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=InvoiceStatus.PARSED,
            invoice_number="S-1",
            period=PERIOD,
            taxable_value=Decimal("100000.00"),
            igst=Decimal("20000.00"),
            total_value=Decimal("120000.00"),
        )
    )
    db_session.commit()

    summary = itc_service.summarise(db_session, business.id, PERIOD)

    assert summary.output_tax.igst == Decimal("20000.00")
    # ₹18,000 of credit against ₹20,000 of liability leaves ₹2,000 in cash.
    assert summary.set_off.cash_payable.igst == Decimal("2000.00")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_itc_endpoint_returns_the_period_position(auth_client, db_session, business):
    save(db_session, business.id, invoice_number="A-1")

    response = auth_client.get(f"/api/v1/itc?period={PERIOD}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == PERIOD
    assert body["available"]["igst"] == "18000.00"
    assert body["reconciled"] is False


def test_itc_endpoint_accepts_a_turnover_override(auth_client, db_session, business):
    """A business with exempt supplies it does not invoice here knows better."""
    save(db_session, business.id, invoice_number="A-1")

    response = auth_client.get(
        f"/api/v1/itc?period={PERIOD}&exempt_turnover=500000&total_turnover=1000000"
    )

    body = response.json()
    assert body["proportionate"]["exempt_ratio"].startswith("0.5")
    assert body["proportionate"]["rule_42_reversal"]["igst"] == "9000.00"


def test_rule37_endpoint_reports_overdue_credit(auth_client, db_session, business):
    save(
        db_session,
        business.id,
        invoice_number="OLD-1",
        invoice_date=date(2025, 6, 1),
        period="2025-06",
    )

    response = auth_client.get("/api/v1/itc/rule37?as_of=2026-04-30")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["overdue"]) == 1
    assert body["reversal"]["igst"] == "18000.00"
    assert body["days"] == 180


def test_set_off_endpoint_refuses_to_cross_cgst_and_sgst(auth_client):
    response = auth_client.post(
        "/api/v1/itc/set-off",
        json={"credit_cgst": "5000", "liability_sgst": "5000"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["steps"] == []
    assert body["cash_payable"]["sgst"] == "5000.00"
    assert body["credit_carried_forward"]["cgst"] == "5000.00"


def test_itc_endpoints_require_authentication(client):
    for path in ("/api/v1/itc", "/api/v1/itc/rule37"):
        assert client.get(path).status_code == 401


def test_itc_does_not_leak_across_tenants(auth_client, db_session, business, other_tenant):
    save(db_session, business.id, invoice_number="A-1")

    response = auth_client.get(
        f"/api/v1/itc?period={PERIOD}",
        headers={"Authorization": f"Bearer {other_tenant}"},
    )

    assert response.json()["available"]["igst"] == "0.00"


@pytest.mark.parametrize("bad", ["2026-4", "202604", "april"])
def test_itc_rejects_a_malformed_period(auth_client, bad):
    assert auth_client.get(f"/api/v1/itc?period={bad}").status_code == 422


# ---------------------------------------------------------------------------
# The reconciliation cap on the input pool
# ---------------------------------------------------------------------------

class TestTheCapComparesInputsWithInputs:
    """A capital purchase must not stop the 2B capping the input pool.

    A run's ``itc_eligible`` covers every purchase the supplier declared,
    capital goods included. ``available`` here is inputs only — Rule 43 holds
    capital credit in its own pool over sixty months. Compared against each
    other, a single machine's credit dwarfs the input pool and the cap never
    binds, so whatever a supplier left out of their own filing is claimed in
    full: an over-claim the 2B on file already contradicts.
    """

    def _run(self, db, business, **kwargs):
        run = ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.COMPLETED,
            **kwargs,
        )
        db.add(run)
        db.commit()
        return run

    def test_a_shortfall_still_caps_the_pool_when_a_machine_was_bought(
        self, db_session, business
    ):
        save(db_session, business.id, invoice_number="INV-1", igst=Decimal("18000.00"))
        save(
            db_session,
            business.id,
            invoice_number="CAP-1",
            igst=Decimal("180000.00"),
            is_capital_good=True,
        )
        # The supplier declared 10,000 of the 18,000 on inputs, and the machine
        # in full: 1,90,000 eligible, of which 1,80,000 is the machine's.
        self._run(
            db_session,
            business,
            itc_eligible=Decimal("190000.00"),
            report={"itc_eligible_capital": "180000.00"},
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.igst == Decimal("10000.00")

    def test_the_capital_pool_is_untouched_by_the_cap(self, db_session, business):
        """Rule 43's sixty months are computed from the books, not from the run."""
        save(
            db_session,
            business.id,
            invoice_number="CAP-1",
            igst=Decimal("180000.00"),
            is_capital_good=True,
        )
        self._run(
            db_session,
            business,
            itc_eligible=Decimal("180000.00"),
            report={"itc_eligible_capital": "180000.00"},
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.total == Decimal("0.00")
        assert summary.proportionate.capital_credit.igst == Decimal("180000.00")
        assert summary.proportionate.capital_credit_this_month.igst == Decimal("3000.00")

    def test_a_period_with_no_capital_goods_is_capped_exactly_as_before(
        self, db_session, business
    ):
        save(db_session, business.id, invoice_number="INV-1", igst=Decimal("18000.00"))
        self._run(
            db_session,
            business,
            itc_eligible=Decimal("10000.00"),
            report={"itc_eligible_capital": "0.00"},
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.igst == Decimal("10000.00")

    @pytest.mark.parametrize("report", [None, {}, {"itc_eligible_capital": "oops"}])
    def test_a_run_without_the_split_is_read_as_having_no_capital_share(
        self, db_session, business, report
    ):
        """Runs recorded before the field existed reproduce the old figure.

        Not the right answer where a machine was bought, but the honest one:
        the evidence is not on the row, and re-running the period supplies it.
        """
        save(db_session, business.id, invoice_number="INV-1", igst=Decimal("18000.00"))
        self._run(
            db_session, business, itc_eligible=Decimal("10000.00"), report=report
        )

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.igst == Decimal("10000.00")

    def test_end_to_end_the_shortfall_reaches_the_screen(self, db_session, business):
        """The whole path: books, a 2B, a real run, then the ITC summary."""
        save(db_session, business.id, invoice_number="INV-1", igst=Decimal("18000.00"))
        save(
            db_session,
            business.id,
            invoice_number="CAP-1",
            igst=Decimal("180000.00"),
            taxable_value=Decimal("1000000.00"),
            is_capital_good=True,
        )

        def declared(number, igst, taxable):
            return GSTR2BRecord(
                supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
                invoice_number=number,
                invoice_date=date(2026, 4, 15),
                period=PERIOD,
                taxable_value=taxable,
                igst=igst,
                total_value=taxable + igst,
            )

        reconciliation.store_gstr2b(
            db_session,
            business.id,
            PERIOD,
            [
                declared("INV-1", Decimal("10000.00"), Decimal("100000.00")),
                declared("CAP-1", Decimal("180000.00"), Decimal("1000000.00")),
            ],
        )
        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.itc_eligible == Decimal("190000.00")

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.igst == Decimal("10000.00")


# ---------------------------------------------------------------------------
# GB021 — purchase_invoices(credit_only=True) narrows in SQL
# ---------------------------------------------------------------------------


class TestCreditOnlyNarrowsInSQL:
    """purchase_invoices(credit_only=True) must exclude non-credit rows in SQL."""

    def test_credit_only_excludes_non_eligible_purchases(self, db_session, business):
        save(db_session, business.id, invoice_number="ELIG-1")
        save(db_session, business.id, invoice_number="BLOCKED-1", itc_eligible=False)
        save(db_session, business.id, invoice_number="RC-1", reverse_charge=True)

        result = itc_service.purchase_invoices(
            db_session, business.id, credit_only=True
        )

        numbers = {inv.invoice_number for inv in result}
        assert "ELIG-1" in numbers
        assert "BLOCKED-1" not in numbers
        assert "RC-1" not in numbers

    def test_without_credit_only_returns_all(self, db_session, business):
        save(db_session, business.id, invoice_number="ELIG-1")
        save(db_session, business.id, invoice_number="BLOCKED-1", itc_eligible=False)
        save(db_session, business.id, invoice_number="RC-1", reverse_charge=True)

        result = itc_service.purchase_invoices(db_session, business.id)

        numbers = {inv.invoice_number for inv in result}
        assert numbers == {"ELIG-1", "BLOCKED-1", "RC-1"}

    def test_rule37_result_is_identical_with_narrowing(self, db_session, business):
        """Narrowing in SQL must not change the Rule 37 answer."""
        save(
            db_session, business.id,
            invoice_number="OLD-1",
            invoice_date=date(2025, 6, 1),
            period="2025-06",
        )
        save(
            db_session, business.id,
            invoice_number="BLOCKED-OLD",
            invoice_date=date(2025, 6, 1),
            period="2025-06",
            itc_eligible=False,
        )

        as_of = date(2026, 4, 30)
        all_inv = itc_service.purchase_invoices(db_session, business.id)
        narrowed = itc_service.purchase_invoices(
            db_session, business.id, credit_only=True
        )

        full = itc_service.rule_37(all_inv, as_of=as_of)
        narrow = itc_service.rule_37(narrowed, as_of=as_of)

        assert full.reversal.igst == narrow.reversal.igst
        assert len(full.overdue) == len(narrow.overdue)
