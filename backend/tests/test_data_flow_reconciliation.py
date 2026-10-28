"""M2 data flow: reconciliation matching produces correct ITC figures.

The matching engine pairs invoices to GSTR-2B records, and from those pairs
it derives how much credit is safe, how much is at risk, and how much was
claimed. This file traces the numbers through the engine and verifies that
the output figures are arithmetically correct for the inputs.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import MatchCategory
from app.services.gstr2b import GSTR2BRecord
from app.services.reconciliation import (
    match,
    summarise_records,
)

ZERO = Decimal("0.00")
PERIOD = "2026-04"
GSTIN = "29AAFCN1234M1ZP"


def _invoice(
    *,
    number: str = "INV-1",
    taxable: str = "10000",
    igst: str = "1800",
    total: str = "11800",
    itc_eligible: bool = True,
    reverse_charge: bool = False,
    is_capital: bool = False,
    gstin: str = GSTIN,
) -> Invoice:
    return Invoice(
        id=hash(number) % 10000,
        business_id=1,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=gstin,
        invoice_number=number,
        invoice_date=date(2026, 4, 10),
        period=PERIOD,
        taxable_value=Decimal(taxable),
        cgst=ZERO,
        sgst=ZERO,
        igst=Decimal(igst),
        cess=ZERO,
        total_value=Decimal(total),
        itc_eligible=itc_eligible,
        reverse_charge=reverse_charge,
        is_capital_good=is_capital,
    )


def _record(
    *,
    number: str = "INV-1",
    taxable: str = "10000",
    igst: str = "1800",
    total: str = "11800",
    itc_available: bool = True,
    gstin: str = GSTIN,
    is_credit_note: bool = False,
) -> GSTR2BRecord:
    return GSTR2BRecord(
        supplier_gstin=gstin,
        supplier_name="Vendor",
        invoice_number=number,
        invoice_date=date(2026, 4, 10),
        period=PERIOD,
        taxable_value=Decimal(taxable),
        cgst=ZERO,
        sgst=ZERO,
        igst=Decimal(igst),
        cess=ZERO,
        total_value=Decimal(total),
        itc_available=itc_available,
        reverse_charge=False,
        document_type="C" if is_credit_note else "R",
    )


# -----------------------------------------------------------------------
# ITC figures follow from the match
# -----------------------------------------------------------------------

class TestMatchedInvoiceClaimsCorrectCredit:

    def test_a_perfect_match_claims_all_booked_tax(self):
        result = match(
            [_invoice()], [_record()], period=PERIOD,
        )
        assert result.itc_eligible == Decimal("1800")
        assert result.itc_at_risk == ZERO
        assert result.itc_claimed == Decimal("1800")

    def test_supplier_declared_less_caps_the_credit(self):
        result = match(
            [_invoice(igst="2000", total="12000")],
            [_record(igst="1800", total="11800")],
            period=PERIOD,
        )
        # Eligible is capped at what the supplier declared
        assert result.itc_eligible == Decimal("1800")
        # The excess is at risk
        assert result.itc_at_risk == Decimal("200")

    def test_supplier_declared_more_claims_only_what_was_booked(self):
        result = match(
            [_invoice(igst="1800", total="11800")],
            [_record(igst="2000", total="12000")],
            period=PERIOD,
        )
        # Can only claim what was booked
        assert result.itc_eligible == Decimal("1800")
        assert result.itc_at_risk == ZERO

    def test_credit_unavailable_on_portal_exposes_all_tax(self):
        result = match(
            [_invoice()],
            [_record(itc_available=False)],
            period=PERIOD,
        )
        assert result.itc_eligible == ZERO
        assert result.itc_at_risk == Decimal("1800")

    def test_missing_in_2b_exposes_the_whole_credit(self):
        result = match(
            [_invoice()], [], period=PERIOD,
        )
        assert result.itc_at_risk == Decimal("1800")
        assert result.itc_eligible == ZERO

    def test_blocked_credit_is_neither_claimed_nor_eligible(self):
        result = match(
            [_invoice(itc_eligible=False)],
            [_record()],
            period=PERIOD,
        )
        assert result.itc_eligible == ZERO
        assert result.itc_at_risk == ZERO
        assert result.itc_claimed == ZERO

    def test_reverse_charge_does_not_contribute_to_itc(self):
        result = match(
            [_invoice(reverse_charge=True)],
            [_record()],
            period=PERIOD,
        )
        assert result.itc_eligible == ZERO
        assert result.itc_claimed == ZERO


# -----------------------------------------------------------------------
# Credit notes reduce the eligible pool
# -----------------------------------------------------------------------

class TestCreditNotesReduceThePool:

    def test_a_credit_note_comes_off_the_eligible_total(self):
        result = match(
            [_invoice()],
            [_record(), _record(number="CN-1", igst="500", total="5500",
                                taxable="5000", is_credit_note=True)],
            period=PERIOD,
        )
        # 1800 eligible from the invoice, minus 500 from the credit note
        assert result.itc_eligible == Decimal("1300")
        assert result.credit_notes == Decimal("500")

    def test_notes_exceeding_the_pool_floor_at_zero(self):
        result = match(
            [_invoice(igst="100", total="10100", taxable="10000")],
            [_record(igst="100", total="10100", taxable="10000"),
             _record(number="CN-1", igst="500", total="5500",
                     taxable="5000", is_credit_note=True)],
            period=PERIOD,
        )
        assert result.itc_eligible == ZERO


# -----------------------------------------------------------------------
# Tolerance and amount comparison
# -----------------------------------------------------------------------

class TestAmountToleranceInComparison:

    def test_within_tolerance_is_a_match(self):
        result = match(
            [_invoice(igst="1800.50")],
            [_record(igst="1800.00")],
            period=PERIOD,
        )
        finding = result.findings[0]
        assert finding.category is MatchCategory.MATCHED
        assert finding.differences == []

    def test_exactly_at_tolerance_is_still_a_match(self):
        result = match(
            [_invoice(igst="1801.00")],
            [_record(igst="1800.00")],
            period=PERIOD,
        )
        finding = result.findings[0]
        assert finding.category is MatchCategory.MATCHED

    def test_one_paisa_past_tolerance_is_a_mismatch(self):
        result = match(
            [_invoice(igst="1801.01")],
            [_record(igst="1800.00")],
            period=PERIOD,
        )
        finding = result.findings[0]
        assert finding.category is MatchCategory.MISMATCHED
        assert any(d.field == "igst" for d in finding.differences)

    def test_custom_tolerance_tightens_the_comparison(self):
        result = match(
            [_invoice(igst="1800.50")],
            [_record(igst="1800.00")],
            period=PERIOD,
            tolerance=Decimal("0.00"),
        )
        finding = result.findings[0]
        assert finding.category is MatchCategory.MISMATCHED


# -----------------------------------------------------------------------
# Invoice number normalization
# -----------------------------------------------------------------------

class TestNormalizationMatchesFuzzyNumbers:

    def test_different_separators_still_match(self):
        """INV/2026/0042 and INV-2026-42 are the same invoice."""
        result = match(
            [_invoice(number="INV/2026/0042")],
            [_record(number="INV-2026-42")],
            period=PERIOD,
        )
        assert result.findings[0].category is MatchCategory.MATCHED
        assert result.findings[0].matched_on == "normalized"

    def test_case_differences_still_match(self):
        result = match(
            [_invoice(number="inv-001")],
            [_record(number="INV-001")],
            period=PERIOD,
        )
        assert result.findings[0].category is MatchCategory.MATCHED

    def test_exact_match_wins_over_normalized(self):
        """If both exact and normalised candidates exist, exact is preferred."""
        result = match(
            [_invoice(number="INV-01")],
            [_record(number="INV-01"), _record(number="INV/1")],
            period=PERIOD,
        )
        assert result.findings[0].matched_on == "exact"


# -----------------------------------------------------------------------
# Multi-invoice reconciliation counts
# -----------------------------------------------------------------------

class TestReconciliationCountsAreConsistent:

    def test_total_invoices_excludes_missing_in_books(self):
        result = match(
            [_invoice(number="INV-1")],
            [_record(number="INV-1"), _record(number="INV-UNKNOWN")],
            period=PERIOD,
        )
        # total_invoices counts only the books side
        assert result.total_invoices == 1
        counts = result.counts()
        assert counts[MatchCategory.MATCHED] == 1
        assert counts[MatchCategory.MISSING_IN_BOOKS] == 1

    def test_itc_figures_sum_across_multiple_invoices(self):
        invoices = [
            _invoice(number="A", igst="1000", total="11000"),
            _invoice(number="B", igst="2000", total="12000"),
        ]
        records = [
            _record(number="A", igst="1000", total="11000"),
            # B is missing from the portal
        ]
        result = match(invoices, records, period=PERIOD)
        assert result.itc_eligible == Decimal("1000")
        assert result.itc_at_risk == Decimal("2000")
        assert result.itc_claimed == Decimal("3000")


# -----------------------------------------------------------------------
# summarise_records — the stored totals of a 2B
# -----------------------------------------------------------------------

class TestSummariseRecordsNetsOffCreditNotes:

    def test_invoices_add_and_notes_subtract(self):
        records = [
            _record(taxable="10000", igst="1800"),
            _record(number="CN-1", taxable="5000", igst="900", is_credit_note=True),
        ]
        totals = summarise_records(records)
        assert totals["total_taxable_value"] == Decimal("5000")
        assert totals["total_igst"] == Decimal("900")

    def test_notes_exceeding_invoices_floor_at_zero(self):
        records = [
            _record(taxable="1000", igst="180"),
            _record(number="CN-1", taxable="5000", igst="900", is_credit_note=True),
        ]
        totals = summarise_records(records)
        assert totals["total_taxable_value"] == ZERO
        assert totals["total_igst"] == ZERO

    def test_document_count_includes_notes(self):
        records = [
            _record(),
            _record(number="CN-1", is_credit_note=True),
        ]
        totals = summarise_records(records)
        assert totals["invoice_count"] == 2


# -----------------------------------------------------------------------
# Capital goods are tracked separately
# -----------------------------------------------------------------------

class TestCapitalGoodsAreTrackedSeparately:

    def test_capital_good_credit_is_split_from_input_credit(self):
        result = match(
            [_invoice(number="CAP-1", igst="18000", total="118000",
                      taxable="100000", is_capital=True)],
            [_record(number="CAP-1", igst="18000", total="118000",
                     taxable="100000")],
            period=PERIOD,
        )
        assert result.itc_eligible == Decimal("18000")
        assert result.itc_eligible_capital == Decimal("18000")
        assert result.input_itc_eligible == ZERO

    def test_mixed_capital_and_input_invoices_split_correctly(self):
        result = match(
            [
                _invoice(number="INP-1", igst="1800"),
                _invoice(number="CAP-1", igst="18000", total="118000",
                         taxable="100000", is_capital=True),
            ],
            [
                _record(number="INP-1", igst="1800"),
                _record(number="CAP-1", igst="18000", total="118000",
                        taxable="100000"),
            ],
            period=PERIOD,
        )
        assert result.itc_eligible == Decimal("19800")
        assert result.itc_eligible_capital == Decimal("18000")
        assert result.input_itc_eligible == Decimal("1800")
