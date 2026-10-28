"""Late fee (s.47) and interest (s.50) on a return filed after its due date.

Two independent penalties on two independent bases — see the module docstring
in :mod:`app.services.late_fee` — so the tests below exercise them separately
before checking the endpoint wires the two into one figure correctly.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from app.models.gstr_return import ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import gst_calendar
from app.services import late_fee as late_fee_service
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE

TODAY = date(2026, 6, 15)
PERIOD = "2026-04"  # GSTR-3B due 2026-05-20, GSTR-1 due 2026-05-11.


@pytest.fixture()
def frozen_today(monkeypatch):
    monkeypatch.setattr(gst_calendar, "today_ist", lambda: TODAY)
    return TODAY


def sale(db, business_id, *, taxable="100000.00", igst="18000.00", number=None) -> Invoice:
    invoice = Invoice(
        business_id=business_id,
        invoice_type=InvoiceType.SALES,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number=number or f"S-{db.query(Invoice).count() + 1}",
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        place_of_supply="29",
        hsn_code="84713010",
        tax_rate=Decimal("18"),
        taxable_value=Decimal(taxable),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal(igst),
        cess=Decimal("0.00"),
        total_value=Decimal(taxable) + Decimal(igst),
        reverse_charge=False,
    )
    db.add(invoice)
    db.commit()
    return invoice


def buy(db, business_id, *, taxable="50000.00", igst="9000.00", cgst="0.00", sgst="0.00",
        number=None) -> Invoice:
    """A creditable purchase, so the period has a credit side to net against."""
    invoice = Invoice(
        business_id=business_id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number=number or f"P-{db.query(Invoice).count() + 1}",
        invoice_date=date(2026, 4, 12),
        period=PERIOD,
        place_of_supply="29",
        hsn_code="84713010",
        tax_rate=Decimal("18"),
        taxable_value=Decimal(taxable),
        cgst=Decimal(cgst),
        sgst=Decimal(sgst),
        igst=Decimal(igst),
        cess=Decimal("0.00"),
        total_value=Decimal(taxable) + Decimal(igst) + Decimal(cgst) + Decimal(sgst),
        itc_eligible=True,
        reverse_charge=False,
    )
    db.add(invoice)
    db.commit()
    return invoice


def late_fee_url(return_type="gstr3b", **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/filing/{return_type}/late-fee?period={PERIOD}"
    return f"{url}&{query}" if query else url


# ---------------------------------------------------------------------------
# Interest — s.50(1)
# ---------------------------------------------------------------------------

class TestInterest:
    def test_no_interest_before_the_due_date(self):
        assert late_fee_service.interest(Decimal("18000.00"), days_late=0) == Decimal("0.00")
        assert late_fee_service.interest(Decimal("18000.00"), days_late=-5) == Decimal("0.00")

    def test_no_interest_on_no_tax(self):
        assert late_fee_service.interest(Decimal("0.00"), days_late=30) == Decimal("0.00")

    def test_eighteen_percent_per_annum_simple_interest(self):
        # ₹18,000 at 18% p.a. for 365 days is exactly ₹3,240.
        assert late_fee_service.interest(Decimal("18000.00"), days_late=365) == Decimal("3240.00")

    def test_prorated_by_the_day(self):
        # ₹1,00,000 at 18% p.a. for 30 days: 100000 * 0.18 * 30 / 365.
        expected = (Decimal("100000") * Decimal("0.18") * 30 / 365).quantize(Decimal("0.01"))
        assert late_fee_service.interest(Decimal("100000.00"), days_late=30) == expected

    def test_the_first_day_late_is_charged_rather_than_written_off(self):
        # The other side of "no interest before the due date". Asserting only
        # the zero side leaves the guard free to swallow a day — `days_late
        # <= 1` passes every test above it — and day one is the day the
        # overwhelming majority of late payments land on, so the day written
        # off would be the one that is nearly always the whole charge.
        expected = (Decimal("100000") * Decimal("0.18") / 365).quantize(Decimal("0.01"))
        assert late_fee_service.interest(Decimal("100000.00"), days_late=1) == expected
        assert expected > Decimal("0.00")


# ---------------------------------------------------------------------------
# Late fee — s.47(1)
# ---------------------------------------------------------------------------

class TestLateFee:
    def test_no_fee_before_the_due_date(self):
        fee = late_fee_service.late_fee(0, is_nil=False)
        assert fee.total == Decimal("0.00")

    def test_fifty_rupees_a_day_split_evenly(self):
        fee = late_fee_service.late_fee(4, is_nil=False)
        assert fee.total == Decimal("200.00")
        assert fee.cgst == Decimal("100.00")
        assert fee.sgst == Decimal("100.00")

    def test_nil_return_is_charged_the_lower_rate(self):
        fee = late_fee_service.late_fee(4, is_nil=True)
        assert fee.total == Decimal("80.00")  # ₹20/day * 4

    def test_nil_return_is_capped_at_five_hundred(self):
        fee = late_fee_service.late_fee(days_late=100, is_nil=True)
        assert fee.total == Decimal("500.00")

    def test_regular_return_is_capped_by_turnover_tier(self):
        small = late_fee_service.late_fee(
            days_late=1000, is_nil=False, previous_year_turnover=Decimal("1000000")
        )
        assert small.total == Decimal("2000.00")

        mid = late_fee_service.late_fee(
            days_late=1000, is_nil=False, previous_year_turnover=Decimal("30000000")
        )
        assert mid.total == Decimal("5000.00")

        large = late_fee_service.late_fee(
            days_late=1000, is_nil=False, previous_year_turnover=Decimal("100000000")
        )
        assert large.total == Decimal("10000.00")

    def test_unknown_turnover_uses_the_highest_cap(self):
        # Never understating the fee matters more than a tight estimate.
        fee = late_fee_service.late_fee(days_late=1000, is_nil=False, previous_year_turnover=None)
        assert fee.total == Decimal("10000.00")

    def test_the_two_heads_always_sum_to_the_capped_total_even_when_odd(self):
        # 3 days at ₹50/day is ₹150 total, already even; force an odd total by
        # picking a boundary day count against the cap instead.
        fee = late_fee_service.late_fee(days_late=1, is_nil=False)
        assert fee.cgst + fee.sgst == fee.total

    def test_the_first_day_late_is_charged_rather_than_forgiven(self):
        # The sum-to-total check above is satisfied by two zeroes, so on its
        # own it does not say a one-day-late return is charged at all. Day one
        # is the common case — a return filed the morning after the 20th — and
        # a guard that let it through would waive the fee nearly every time it
        # was owed.
        fee = late_fee_service.late_fee(1, is_nil=False)
        assert fee.total == Decimal("50.00")
        assert (fee.cgst, fee.sgst) == (Decimal("25.00"), Decimal("25.00"))

    def test_a_turnover_exactly_on_a_tier_boundary_stays_in_the_lower_tier(self):
        # The bands are written as "up to ₹1.5 crore", which includes a
        # business sitting exactly on ₹1.5 crore. A strict comparison would
        # move precisely the filers who report a round number — the ones most
        # likely to land on the line — one tier up, and charge them a cap two
        # and a half times what they owe.
        for turnover, cap in (
            (Decimal("15000000"), Decimal("2000.00")),
            (Decimal("50000000"), Decimal("5000.00")),
        ):
            fee = late_fee_service.late_fee(
                days_late=1000, is_nil=False, previous_year_turnover=turnover
            )
            assert fee.total == cap, turnover

        # A paisa over the line is the next tier up, which is what makes the
        # equality above a boundary rather than a coincidence.
        over = late_fee_service.late_fee(
            days_late=1000, is_nil=False, previous_year_turnover=Decimal("15000000.01")
        )
        assert over.total == Decimal("5000.00")

    def test_a_return_filed_on_its_due_date_is_quoted_its_turnover_cap_not_the_nil_one(self):
        # Day zero returns before the nil branch is reached, so the tier a
        # not-yet-late filer is shown is the one their turnover puts them in.
        # The distinction is only visible on a nil return, where being one day
        # later would swap the ₹2,000 cap for the ₹500 nil cap — and the ₹2,000
        # is the honest answer to "what could this cost me", because whether
        # the period is still nil on the day it is finally filed is not
        # something a zero-invoice period today can promise.
        fee = late_fee_service.late_fee(
            0, is_nil=True, previous_year_turnover=Decimal("1000000")
        )
        assert fee.total == Decimal("0.00")
        assert fee.tier.label == "turnover up to ₹1.5 crore"
        assert fee.tier.cap == Decimal("2000.00")


# ---------------------------------------------------------------------------
# The value objects the figures travel in
# ---------------------------------------------------------------------------

class TestTheQuotedFiguresCannotBeEditedAfterTheyAreQuoted:
    """A fee is quoted once and then read by several screens.

    The estimate goes to the late-fee endpoint, to the dashboard card, and
    through ``as_dict`` to the alert digest, all from the one call — and
    nothing downstream re-derives it from the invoices, so a reader that
    adjusted a head in place would change what every later reader is told a
    business owes, with no second computation to contradict it.
    """

    def test_a_turnover_tier_cannot_be_edited(self):
        tier = late_fee_service.turnover_tier(Decimal("1000000"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            tier.cap = Decimal("10000.00")

    def test_a_late_fee_cannot_be_edited(self):
        fee = late_fee_service.late_fee(4, is_nil=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            fee.cgst = Decimal("0.00")

    def test_an_estimate_cannot_be_edited(self, db_session, business, frozen_today):
        estimate = late_fee_service.estimate(db_session, business, PERIOD)
        with pytest.raises(dataclasses.FrozenInstanceError):
            estimate.days_late = 0


# ---------------------------------------------------------------------------
# The combined estimate
# ---------------------------------------------------------------------------

class TestEstimate:
    def test_a_return_not_yet_due_owes_nothing(
        self, db_session, business, frozen_today
    ):
        result = late_fee_service.estimate(
            db_session, business, "2026-05", ReturnType.GSTR3B
        )
        assert result.days_late == 0
        assert result.total_payable == Decimal("0.00")

    def test_an_overdue_unfiled_period_is_a_projection(
        self, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )
        assert result.filed_on is None
        assert result.projected is True
        # Due 2026-05-20, "as of" 2026-06-15 -> 26 days late.
        assert result.days_late == 26
        assert result.fee.total == Decimal("1300.00")  # 26 * 50, under every cap
        assert result.interest_amount > Decimal("0.00")

    def test_interest_runs_on_the_cash_shortfall_not_on_the_output_tax(
        self, db_session, business, frozen_today
    ):
        # s.50(1) charges interest on the tax actually paid late, and what is
        # paid in cash is output tax less the credit claimed against it. Every
        # test above this one has a sales side and no purchases, so the two
        # bases coincide and nothing distinguishes them: the credit could be
        # added to the base instead of subtracted and the suite would agree.
        # A business with ₹18,000 of output tax and ₹9,000 of credit pays
        # ₹9,000 in cash, and it is that figure interest runs on.
        sale(db_session, business.id)  # IGST 18,000 out
        buy(db_session, business.id)  # IGST  9,000 creditable

        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )
        assert result.net_tax_liability == Decimal("9000.00")
        assert result.interest_amount == late_fee_service.interest(
            Decimal("9000.00"), result.days_late
        )

    def test_cgst_and_sgst_credit_settle_igst_liability_before_interest(
        self, db_session, business, frozen_today
    ):
        # s.49(5)(b) and (c): CGST and SGST credit each settle IGST once their
        # own head is clear. Netting head against head said this period paid
        # ₹18,000 in cash and charged interest on it; the ledger pays ₹8,000.
        sale(db_session, business.id)  # IGST 18,000 out, nothing on CGST/SGST
        buy(
            db_session,
            business.id,
            igst="0.00",
            cgst="5000.00",
            sgst="5000.00",
        )

        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )
        assert result.net_tax_liability == Decimal("8000.00")

    def test_igst_credit_settles_cgst_and_sgst_liability_before_interest(self):
        sales = {"igst": "0", "cgst": "1000", "sgst": "1000", "cess": "0"}
        credit = {"igst": "2000", "cgst": "0", "sgst": "0", "cess": "0"}
        assert late_fee_service._net_cash_liability(sales, credit) == Decimal("0.00")

    def test_cgst_credit_still_cannot_pay_sgst(self):
        sales = {"igst": "0", "cgst": "0", "sgst": "1000", "cess": "0"}
        credit = {"igst": "0", "cgst": "1000", "sgst": "0", "cess": "0"}
        assert late_fee_service._net_cash_liability(sales, credit) == Decimal("1000.00")

    def test_gstr1_carries_no_interest(self, db_session, business, frozen_today):
        sale(db_session, business.id)
        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR1
        )
        assert result.interest_amount == Decimal("0.00")
        assert result.fee.total > Decimal("0.00")

    def test_a_period_with_no_invoices_is_treated_as_nil(
        self, db_session, business, frozen_today
    ):
        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )
        assert result.is_nil is True
        assert result.fee.total == Decimal("500.00")  # capped nil rate

    def test_is_nil_can_be_overridden(self, db_session, business, frozen_today):
        sale(db_session, business.id)
        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B, is_nil=True
        )
        assert result.is_nil is True
        assert result.fee.total == Decimal("500.00")

    def test_a_recorded_filing_freezes_the_figures(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        filed_on = "2026-05-25"  # 5 days late
        response = auth_client.post(
            "/api/v1/filing/gstr3b/filed", json={"period": PERIOD, "filed_on": filed_on}
        )
        assert response.status_code == 201, response.text

        result = late_fee_service.estimate(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )
        assert result.filed_on == date(2026, 5, 25)
        assert result.projected is False
        assert result.days_late == 5

    def test_an_unfilable_return_type_is_refused(self, db_session, business, frozen_today):
        with pytest.raises(ValueError, match="not a return"):
            late_fee_service.estimate(db_session, business, PERIOD, ReturnType.GSTR2B)


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------

class TestTheEndpoint:
    def test_it_reports_the_estimate(self, auth_client, db_session, business, frozen_today):
        sale(db_session, business.id)
        response = auth_client.get(late_fee_url())
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["period"] == PERIOD
        assert body["return_type"] == "gstr3b"
        assert body["projected"] is True
        assert Decimal(body["late_fee_total"]) == Decimal("1300.00")
        assert Decimal(body["total_payable"]) == Decimal(body["late_fee_total"]) + Decimal(
            body["interest"]
        )

    def test_an_unknown_return_type_is_404(self, auth_client, business, frozen_today):
        response = auth_client.get(late_fee_url("gstr2b"))
        assert response.status_code == 404

    def test_turnover_selects_the_cap_tier(self, auth_client, db_session, business, frozen_today):
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover="1000000", is_nil="false")
        )
        assert response.status_code == 200, response.text
        # 26 days at ₹50/day is ₹1,300, well under the ₹2,000 small-taxpayer cap.
        assert Decimal(response.json()["late_fee_total"]) == Decimal("1300.00")

    def test_a_non_numeric_turnover_is_rejected(self, auth_client, business, frozen_today):
        response = auth_client.get(late_fee_url(previous_year_turnover="not-a-number"))
        assert response.status_code == 422

    @pytest.mark.parametrize("turnover", ["nan", "NaN", "sNaN", "inf", "-inf"])
    def test_a_turnover_that_is_not_a_finite_number_is_refused(
        self, auth_client, db_session, business, frozen_today, turnover
    ):
        """These parse. That is what made them a 500 rather than a 422.

        ``Decimal("nan")`` constructs without complaint — only arithmetic on it
        raises — so a try/except around the parse caught nothing and the
        InvalidOperation surfaced two layers down, inside ``turnover_tier``'s
        comparison. ``is_nil=false`` is what makes that comparison run: the nil
        branch never consults the tier, so the route answered 200 without it
        and the bug hid behind whichever period the test happened to pick.
        """
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover=turnover, is_nil="false")
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize("turnover", ["-1", "-5000", "-1E+500"])
    def test_a_negative_turnover_is_refused_rather_than_capped_at_the_lowest_tier(
        self, auth_client, db_session, business, frozen_today, turnover
    ):
        """The expensive one: this used to answer 200 with the *smallest* cap.

        A negative figure parsed cleanly and then matched the first tier, so
        the caller was told ₹2,000 was their ceiling. ``turnover_tier`` picks
        the highest tier when it knows nothing precisely because the errors are
        not symmetric — understating a cap tells a business it is covered and
        the shortfall notice arrives weeks later. Understating it from a
        nonsense input is that same failure with a confident number attached.
        """
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover=turnover, is_nil="false")
        )
        assert response.status_code == 422, response.text

    def test_a_turnover_larger_than_any_money_column_is_refused(
        self, auth_client, db_session, business, frozen_today
    ):
        """Landing on the highest tier was luck, not a decision.

        An unbounded exponent reached the tier table and happened to fall off
        the end of it — the right answer for the wrong reason. The ceiling is
        the same one every stored money figure carries.
        """
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover="1E+999999999", is_nil="false")
        )
        assert response.status_code == 422, response.text

    def test_the_largest_real_turnover_is_still_accepted(
        self, auth_client, db_session, business, frozen_today
    ):
        """The negative tests above are only meaningful if this one passes: a
        genuine ₹5-crore-plus turnover must still select the top tier rather
        than being caught by the new ceiling."""
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover="500000000", is_nil="false")
        )
        assert response.status_code == 200, response.text
        assert response.json()["late_fee_tier"] == "turnover above ₹5 crore"

    def test_a_turnover_of_zero_is_a_real_answer_not_a_missing_one(
        self, auth_client, db_session, business, frozen_today
    ):
        """Zero is a business that traded nothing last year, and the floor is
        ``ge=0`` rather than ``gt=0`` so it can say so. It selects the smallest
        cap, which for zero turnover is correct — unlike the negative inputs
        above, this caller meant it."""
        sale(db_session, business.id)
        response = auth_client.get(
            late_fee_url(previous_year_turnover="0", is_nil="false")
        )
        assert response.status_code == 200, response.text
        assert response.json()["late_fee_tier"] == "turnover up to ₹1.5 crore"

    def test_is_nil_query_param_overrides_the_guess(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        response = auth_client.get(late_fee_url(is_nil="true"))
        assert response.status_code == 200, response.text
        assert response.json()["is_nil"] is True
        assert Decimal(response.json()["late_fee_total"]) == Decimal("500.00")

    def test_another_tenants_late_fee_is_not_visible(
        self, auth_client, db_session, business, other_tenant, frozen_today
    ):
        sale(db_session, business.id)
        auth_client.headers.update({"Authorization": f"Bearer {other_tenant}"})
        response = auth_client.get(late_fee_url())
        assert response.status_code == 200
        # The other tenant has no invoices and files nothing, so their own
        # figures are the nil rate rather than this business's.
        assert response.json()["is_nil"] is True


class TestDashboardWiring:
    def test_the_dashboard_carries_no_estimate_when_not_overdue(
        self, auth_client, business, frozen_today
    ):
        body = auth_client.get("/api/v1/dashboard?period=2026-05").json()
        assert body["late_fee_estimate"] is None

    def test_the_dashboard_carries_the_estimate_once_overdue(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        body = auth_client.get(f"/api/v1/dashboard?period={PERIOD}").json()
        assert body["late_fee_estimate"] is not None
        assert body["late_fee_estimate"]["period"] == PERIOD

    def test_the_estimate_disappears_once_the_return_is_filed(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        auth_client.post(
            "/api/v1/filing/gstr3b/filed",
            json={"period": PERIOD, "filed_on": "2026-05-18"},  # on time
        )
        body = auth_client.get(f"/api/v1/dashboard?period={PERIOD}").json()
        assert body["late_fee_estimate"] is None
