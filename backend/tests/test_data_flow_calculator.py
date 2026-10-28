"""M2 data flow: GST calculator — CGST/SGST/IGST splits and invoice totals.

``on_taxable`` and ``from_inclusive`` are the two core tax computations, and
neither had a direct unit test. Every other figure in the product — the ITC
summary, the GSTR-1, the GSTR-3B, and the CSV export — is downstream of
what these two functions return, so a paisa of drift here costs a paisa on
every number the business sees.

``build_invoice`` is the line-by-line aggregation: quantities, discounts,
per-rate summaries, rounding. ``resolve_state`` decides which of those two
functions is called, so a wrong answer there puts the tax in the wrong
government's ledger.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.gst_calculator import (
    PAISA,
    GstInputError,
    LineInput,
    amount_in_words,
    build_invoice,
    check_rate,
    from_inclusive,
    on_taxable,
    resolve_state,
)

ZERO = Decimal("0.00")


# -----------------------------------------------------------------------
# on_taxable — tax added on top of a known taxable value
# -----------------------------------------------------------------------

class TestOnTaxableIntraState:
    """Intra-state: CGST and SGST are each rate/2, IGST is zero."""

    def test_18_percent_on_one_lakh(self):
        split = on_taxable(Decimal("100000"), Decimal("18"), interstate=False)
        assert split.cgst == Decimal("9000.00")
        assert split.sgst == Decimal("9000.00")
        assert split.igst == ZERO
        assert split.taxable_value == Decimal("100000.00")
        assert split.total == Decimal("118000.00")

    def test_5_percent_on_a_value_that_rounds(self):
        # 2.5% of 999.99 = 24.99975 → 25.00 (ROUND_HALF_UP)
        split = on_taxable(Decimal("999.99"), Decimal("5"), interstate=False)
        assert split.cgst == Decimal("25.00")
        assert split.sgst == Decimal("25.00")
        assert split.cgst == split.sgst

    def test_zero_rate_produces_zero_tax(self):
        split = on_taxable(Decimal("50000"), Decimal("0"), interstate=False)
        assert split.total_tax == ZERO
        assert split.total == Decimal("50000.00")

    def test_cgst_always_equals_sgst_on_intra_state(self):
        for rate_str in ("0.25", "1.5", "3", "5", "12", "18", "28"):
            split = on_taxable(Decimal("12345.67"), Decimal(rate_str), interstate=False)
            assert split.cgst == split.sgst, f"Mismatch at {rate_str}%"


class TestOnTaxableInterState:
    """Inter-state: IGST is the full rate, CGST and SGST are zero."""

    def test_18_percent_on_one_lakh(self):
        split = on_taxable(Decimal("100000"), Decimal("18"), interstate=True)
        assert split.igst == Decimal("18000.00")
        assert split.cgst == ZERO
        assert split.sgst == ZERO

    def test_28_percent_on_a_fractional_value(self):
        # 28% of 1234.56 = 345.6768 → 345.68
        split = on_taxable(Decimal("1234.56"), Decimal("28"), interstate=True)
        assert split.igst == Decimal("345.68")

    def test_total_equals_taxable_plus_tax(self):
        split = on_taxable(Decimal("99999.99"), Decimal("12"), interstate=True)
        assert split.total == split.taxable_value + split.total_tax


# -----------------------------------------------------------------------
# from_inclusive — tax backed out of a gross price
# -----------------------------------------------------------------------

class TestFromInclusiveIntraState:
    """Back out CGST and SGST from a price that includes tax."""

    def test_118000_at_18_percent_gives_back_100000_taxable(self):
        split = from_inclusive(Decimal("118000"), Decimal("18"), interstate=False)
        assert split.taxable_value == Decimal("100000.00")
        assert split.cgst == Decimal("9000.00")
        assert split.sgst == Decimal("9000.00")

    def test_taxable_plus_tax_equals_gross(self):
        """The whole point: gross is honoured to the paisa."""
        for gross in ("11800", "999.99", "1.01", "100000.01"):
            split = from_inclusive(Decimal(gross), Decimal("18"), interstate=False)
            assert split.total == Decimal(gross).quantize(PAISA), f"Failed on {gross}"

    def test_cgst_equals_sgst_on_intra_state_inclusive(self):
        split = from_inclusive(Decimal("10500"), Decimal("5"), interstate=False)
        assert split.cgst == split.sgst


class TestFromInclusiveInterState:
    """Back out IGST from a gross price."""

    def test_igst_is_computed_and_taxable_is_the_remainder(self):
        split = from_inclusive(Decimal("118000"), Decimal("18"), interstate=True)
        assert split.igst == Decimal("18000.00")
        assert split.taxable_value == Decimal("100000.00")
        assert split.cgst == ZERO
        assert split.sgst == ZERO

    def test_odd_gross_still_adds_up(self):
        split = from_inclusive(Decimal("777.77"), Decimal("12"), interstate=True)
        assert split.total == Decimal("777.77")


# -----------------------------------------------------------------------
# resolve_state — which government gets the tax
# -----------------------------------------------------------------------

class TestResolveState:
    """The state code from a GSTIN, an explicit code, or both."""

    def test_a_gstin_gives_its_state_code(self):
        assert resolve_state("27AAPFU0939F1ZV", None, who="Supplier") == "27"

    def test_an_explicit_code_is_used_when_no_gstin(self):
        assert resolve_state(None, "27", who="Buyer") == "27"

    def test_both_agreeing_is_fine(self):
        assert resolve_state("27AAPFU0939F1ZV", "27", who="Supplier") == "27"

    def test_both_disagreeing_is_refused(self):
        with pytest.raises(GstInputError, match="registered in state 27"):
            resolve_state("27AAPFU0939F1ZV", "29", who="Supplier")

    def test_neither_gives_none(self):
        assert resolve_state(None, None, who="Buyer") is None

    def test_an_invalid_gstin_is_refused(self):
        with pytest.raises(GstInputError, match="invalid"):
            resolve_state("INVALID", None, who="Buyer")

    def test_an_invalid_state_code_is_refused(self):
        with pytest.raises(GstInputError, match="not a GST state code"):
            resolve_state(None, "ZZ", who="Buyer")


# -----------------------------------------------------------------------
# build_invoice — line-by-line aggregation
# -----------------------------------------------------------------------

class TestBuildInvoice:
    """Multi-line invoice builds the right totals."""

    def test_a_single_line_invoice_totals_correctly(self):
        items = [LineInput("Widget", Decimal("10"), Decimal("100"), Decimal("18"))]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="27",
            invoice_date=date(2026, 4, 1),
        )
        assert inv.taxable_value == Decimal("1000.00")
        assert inv.cgst == Decimal("90.00")
        assert inv.sgst == Decimal("90.00")
        assert inv.igst == ZERO
        assert not inv.interstate

    def test_an_interstate_invoice_puts_all_tax_in_igst(self):
        items = [LineInput("Widget", Decimal("10"), Decimal("100"), Decimal("18"))]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="29",
            invoice_date=date(2026, 4, 1),
        )
        assert inv.igst == Decimal("180.00")
        assert inv.cgst == ZERO
        assert inv.sgst == ZERO
        assert inv.interstate

    def test_discount_reduces_the_taxable_value(self):
        items = [LineInput(
            "Widget", Decimal("10"), Decimal("100"), Decimal("18"),
            discount_percent=Decimal("10"),
        )]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="27",
            invoice_date=date(2026, 4, 1),
        )
        # 10 x 100 = 1000, less 10% = 900 taxable
        assert inv.taxable_value == Decimal("900.00")

    def test_rate_summary_agrees_with_the_lines(self):
        items = [
            LineInput("A", Decimal("5"), Decimal("200"), Decimal("5")),
            LineInput("B", Decimal("3"), Decimal("300"), Decimal("18")),
        ]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="27",
            invoice_date=date(2026, 4, 1),
        )
        assert len(inv.rate_summary) == 2
        # Rate summary must be sorted by rate
        assert inv.rate_summary[0].rate == Decimal("5")
        assert inv.rate_summary[1].rate == Decimal("18")
        # Totals from rate_summary must agree with invoice totals
        assert sum(s.taxable_value for s in inv.rate_summary) == inv.taxable_value
        assert sum(s.cgst for s in inv.rate_summary) == inv.cgst
        assert sum(s.sgst for s in inv.rate_summary) == inv.sgst

    def test_round_off_goes_to_nearest_rupee(self):
        items = [LineInput("A", Decimal("1"), Decimal("100.50"), Decimal("18"))]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="29",
            invoice_date=date(2026, 4, 1),
            round_to_rupee=True,
        )
        # taxable: 100.50, igst: 18.09, exact: 118.59, grand: 119.00
        assert inv.grand_total == Decimal("119.00")
        assert inv.round_off == inv.grand_total - (inv.taxable_value + inv.total_tax)

    def test_round_off_disabled_gives_exact_total(self):
        items = [LineInput("A", Decimal("1"), Decimal("100.50"), Decimal("18"))]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="29",
            invoice_date=date(2026, 4, 1),
            round_to_rupee=False,
        )
        assert inv.grand_total == inv.taxable_value + inv.total_tax
        assert inv.round_off == ZERO

    def test_an_invalid_rate_is_refused(self):
        items = [LineInput("Bad", Decimal("1"), Decimal("100"), Decimal("17"))]
        with pytest.raises(GstInputError, match="not a GST rate"):
            build_invoice(
                items,
                supplier_state="27",
                place_of_supply="27",
                invoice_date=date(2026, 4, 1),
            )

    def test_multiple_lines_at_different_rates_aggregate_correctly(self):
        items = [
            LineInput("A", Decimal("1"), Decimal("10000"), Decimal("5")),
            LineInput("B", Decimal("1"), Decimal("10000"), Decimal("18")),
        ]
        inv = build_invoice(
            items,
            supplier_state="27",
            place_of_supply="27",
            invoice_date=date(2026, 4, 1),
        )
        assert inv.taxable_value == Decimal("20000.00")
        # 5% of 10000: CGST=250, SGST=250
        # 18% of 10000: CGST=900, SGST=900
        assert inv.cgst == Decimal("1150.00")
        assert inv.sgst == Decimal("1150.00")


# -----------------------------------------------------------------------
# amount_in_words — Indian numbering system
# -----------------------------------------------------------------------

class TestAmountInWords:
    def test_zero(self):
        assert amount_in_words(Decimal("0")) == "Rupees Zero Only"

    def test_simple_amount(self):
        assert amount_in_words(Decimal("100")) == "Rupees One Hundred Only"

    def test_paise(self):
        assert amount_in_words(Decimal("1.50")) == "Rupees One and Fifty Paise Only"

    def test_lakh(self):
        result = amount_in_words(Decimal("100000"))
        assert "One Lakh" in result

    def test_crore(self):
        result = amount_in_words(Decimal("10000000"))
        assert "One Crore" in result

    def test_complex_amount(self):
        result = amount_in_words(Decimal("1234567.89"))
        assert "Twelve Lakh" in result
        assert "Thirty Four Thousand" in result
        assert "Eighty Nine Paise" in result


# -----------------------------------------------------------------------
# check_rate — the rate validation gate
# -----------------------------------------------------------------------

class TestCheckRate:
    def test_valid_rates_pass(self):
        for rate_str in ("0", "0.25", "5", "12", "18", "28"):
            check_rate(Decimal(rate_str))

    def test_invalid_rate_is_refused(self):
        with pytest.raises(GstInputError, match="not a GST rate"):
            check_rate(Decimal("15"))

    def test_the_error_quotes_the_rate_back(self):
        with pytest.raises(GstInputError, match="17"):
            check_rate(Decimal("17"))
