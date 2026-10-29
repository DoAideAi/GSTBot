"""M2 data flow: filing aggregation sums from invoices to return JSON.

GSTR-1 and GSTR-3B are the final output: whatever this module produces is
what a business files on the portal, and a wrong figure carries interest
from the moment the return is submitted. This traces the aggregation from
stored invoices to the generated JSON, checking that every figure the
portal cares about (rate-wise splits, B2B/B2CL/B2CS classification, and
the GSTR-3B table 4 ITC position) is arithmetically correct for the
input invoices.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import filing as filing_service

ZERO = Decimal("0.00")
PERIOD = "2026-04"


CUSTOMER_INTER = "29AAGCB7383J1Z4"   # valid, state 29 (interstate from 27)
CUSTOMER_INTRA = "27AABCT1234D1ZU"   # valid, state 27 (same state as business)


def _sale(db, business, *, number="S-1", taxable="10000", cgst="900", sgst="900",
          igst="0", cess="0", total="11800", gstin: str | None = CUSTOMER_INTRA,
          rate="18", pos=None, hsn="8471", rc=False) -> Invoice:
    inv = Invoice(
        business_id=business.id,
        invoice_type=InvoiceType.SALES,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=gstin,
        counterparty_name="Customer",
        invoice_number=number,
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        place_of_supply=pos,
        hsn_code=hsn,
        tax_rate=Decimal(rate),
        taxable_value=Decimal(taxable),
        cgst=Decimal(cgst),
        sgst=Decimal(sgst),
        igst=Decimal(igst),
        cess=Decimal(cess),
        total_value=Decimal(total),
        reverse_charge=rc,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# -----------------------------------------------------------------------
# GSTR-1: B2B / B2CL / B2CS classification
# -----------------------------------------------------------------------

class TestGstr1Classification:

    def test_a_registered_sale_lands_in_b2b(self, db_session, business):
        _sale(db_session, business)
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        assert "b2b" in doc
        assert doc["b2b"][0]["ctin"] == CUSTOMER_INTRA

    def test_an_unregistered_intra_state_sale_lands_in_b2cs(self, db_session, business):
        _sale(db_session, business, gstin=None, pos=business.state_code)
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        assert "b2cs" in doc
        assert "b2b" not in doc

    def test_a_large_unregistered_interstate_sale_lands_in_b2cl(self, db_session, business):
        _sale(db_session, business, gstin=None, pos="29",
              taxable="200000", igst="36000", cgst="0", sgst="0",
              total="236000")
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        assert "b2cl" in doc
        assert doc["b2cl"][0]["pos"] == "29"


# -----------------------------------------------------------------------
# GSTR-1: money cross-foots
# -----------------------------------------------------------------------

class TestGstr1MoneyCrossFoot:

    def test_b2b_item_amounts_match_the_invoice(self, db_session, business):
        _sale(db_session, business, taxable="50000", cgst="4500", sgst="4500",
              total="59000", rate="18")
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        inv_block = doc["b2b"][0]["inv"][0]
        itm = inv_block["itms"][0]["itm_det"]
        assert itm["txval"] == 50000.0
        assert itm["camt"] == 4500.0
        assert itm["samt"] == 4500.0

    def test_b2cs_aggregates_by_place_and_rate(self, db_session, business):
        _sale(db_session, business, number="S-1", gstin=None,
              pos=business.state_code, taxable="5000", cgst="250",
              sgst="250", total="5500", rate="5")
        _sale(db_session, business, number="S-2", gstin=None,
              pos=business.state_code, taxable="3000", cgst="150",
              sgst="150", total="3300", rate="5")
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        bucket = doc["b2cs"][0]
        assert bucket["txval"] == 8000.0
        assert bucket["camt"] == 400.0
        assert bucket["samt"] == 400.0

    def test_hsn_summary_sums_by_code_and_rate(self, db_session, business):
        _sale(db_session, business, number="S-1", hsn="8471", rate="18",
              taxable="10000", cgst="900", sgst="900", total="11800")
        _sale(db_session, business, number="S-2", hsn="8471", rate="18",
              taxable="5000", cgst="450", sgst="450", total="5900")
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        hsn_entry = doc["hsn"]["data"][0]
        assert hsn_entry["txval"] == 15000.0
        assert hsn_entry["camt"] == 1350.0
        assert hsn_entry["samt"] == 1350.0


# -----------------------------------------------------------------------
# GSTR-3B table 3.1: output tax
# -----------------------------------------------------------------------

class TestGstr3bOutputTax:

    def test_outward_taxable_sums_all_taxed_sales(self, db_session, business):
        _sale(db_session, business, number="S-1", taxable="10000",
              cgst="900", sgst="900", total="11800")
        _sale(db_session, business, number="S-2", taxable="20000",
              cgst="1800", sgst="1800", total="23600")
        doc = filing_service.build_gstr3b(db_session, business, PERIOD)
        sup = doc["sup_details"]["osup_det"]
        assert sup["txval"] == 30000.0
        assert sup["camt"] == 2700.0
        assert sup["samt"] == 2700.0

    def test_a_reverse_charge_sale_is_not_this_business_s_liability(self, db_session, business):
        """P16 M2: under s.9(3)/9(4) the recipient pays the tax on this supply.

        It counted as output tax, so 3.1(a) declared it, the set-off paid it and
        the customer paid it again at their own 3.1(d). The supplier reports
        the value with the supplies it pays no tax on, at 3.1(c).
        """
        _sale(db_session, business, number="S-1", taxable="10000",
              cgst="900", sgst="900", total="11800")
        _sale(db_session, business, number="S-RCM", taxable="50000",
              cgst="4500", sgst="4500", total="59000", rc=True)

        doc = filing_service.build_gstr3b(db_session, business, PERIOD)

        sup = doc["sup_details"]["osup_det"]
        assert sup["txval"] == 10000.0
        assert sup["camt"] == 900.0
        assert sup["samt"] == 900.0
        assert doc["sup_details"]["osup_nil_exmp"]["txval"] == 50000.0
        assert doc["gstbot_cash_payable"] == "1800.00"

    def test_gstr1_still_lists_the_reverse_charge_sale_flagged(self, db_session, business):
        # The document is the recipient's evidence; only the 3B liability moves.
        _sale(db_session, business, number="S-RCM", taxable="50000",
              cgst="4500", sgst="4500", total="59000", rc=True)
        doc = filing_service.build_gstr1(db_session, business, PERIOD)
        (party,) = doc["b2b"]
        (inv,) = party["inv"]
        assert inv["rchrg"] == "Y"

    def test_nil_rated_sales_go_to_exempt_block(self, db_session, business):
        _sale(db_session, business, taxable="10000", cgst="0", sgst="0",
              igst="0", total="10000", rate="0")
        doc = filing_service.build_gstr3b(db_session, business, PERIOD)
        assert doc["sup_details"]["osup_nil_exmp"]["txval"] == 10000.0

    def test_interstate_unregistered_sales_appear_in_table_3_2(self, db_session, business):
        _sale(db_session, business, gstin=None, pos="29",
              taxable="50000", igst="9000", cgst="0", sgst="0",
              total="59000")
        doc = filing_service.build_gstr3b(db_session, business, PERIOD)
        unreg = doc["inter_sup"]["unreg_details"]
        assert len(unreg) == 1
        assert unreg[0]["pos"] == "29"
        assert unreg[0]["txval"] == 50000.0


# -----------------------------------------------------------------------
# CSV export agrees with the JSON
# -----------------------------------------------------------------------

class TestCsvExportFidelity:

    def test_csv_amounts_match_stored_values(self, db_session, business):
        _sale(db_session, business, taxable="12345.67", cgst="1111.11",
              sgst="1111.11", total="14567.89")
        text = filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
        reader = csv.DictReader(io.StringIO(text))
        [row] = list(reader)
        assert row["taxable_value"] == "12345.67"
        assert row["cgst"] == "1111.11"
        assert row["sgst"] == "1111.11"

    def test_csv_total_value_uses_derived_value_not_stored(self, db_session, business):
        """A stored total of 0 should not make the CSV say the invoice is worthless."""
        _sale(db_session, business, taxable="10000", cgst="900",
              sgst="900", total="0")
        text = filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
        reader = csv.DictReader(io.StringIO(text))
        [row] = list(reader)
        # Should derive: 10000 + 900 + 900 = 11800
        assert Decimal(row["total_value"]) == Decimal("11800.00")


# -----------------------------------------------------------------------
# Validation catches inter/intra state split errors
# -----------------------------------------------------------------------

class TestValidationCatchesSplitErrors:

    def test_interstate_supply_with_cgst_sgst_is_flagged(self, db_session, business):
        inv = _sale(db_session, business, gstin=CUSTOMER_INTER,
                    pos="29", cgst="900", sgst="900", igst="0")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        assert any("Inter-state" in i.message for i in issues)

    def test_intra_state_supply_with_igst_is_flagged(self, db_session, business):
        inv = _sale(db_session, business, gstin=CUSTOMER_INTRA,
                    pos=business.state_code, cgst="0", sgst="0", igst="1800")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        assert any("Intra-state" in i.message for i in issues)

    def test_unequal_cgst_and_sgst_on_intra_state_is_flagged(self, db_session, business):
        inv = _sale(db_session, business, gstin=CUSTOMER_INTRA,
                    pos=business.state_code, cgst="900", sgst="800", igst="0")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        assert any("must be equal" in i.message for i in issues)


# -----------------------------------------------------------------------
# Validation catches tax-rate arithmetic errors
# -----------------------------------------------------------------------

class TestValidationCatchesTaxArithmeticErrors:

    def test_tax_matching_rate_validates_clean(self, db_session, business):
        inv = _sale(db_session, business, taxable="10000", cgst="900",
                    sgst="900", rate="18")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        rate_issues = [i for i in issues if i.field == "tax_rate"]
        assert rate_issues == []

    def test_tax_not_matching_rate_is_an_error(self, db_session, business):
        inv = _sale(db_session, business, taxable="10000", cgst="1000",
                    sgst="1000", rate="18")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        rate_issues = [i for i in issues if i.field == "tax_rate"]
        assert len(rate_issues) == 1
        assert rate_issues[0].severity is filing_service.Severity.ERROR

    def test_tax_on_zero_taxable_value_is_an_error(self, db_session, business):
        inv = _sale(db_session, business, taxable="0", cgst="900",
                    sgst="900", total="1800")
        issues = filing_service.validate_invoice(
            inv, business_state=business.state_code, period=PERIOD,
        )
        assert any("zero" in i.message.lower() for i in issues)


# -----------------------------------------------------------------------
# Period format conversion
# -----------------------------------------------------------------------

class TestPortalPeriodConversion:

    def test_yyyy_mm_to_mmyyyy(self):
        assert filing_service.to_portal_period("2026-04") == "042026"
        assert filing_service.to_portal_period("2026-12") == "122026"

    def test_portal_date_format(self):
        assert filing_service.to_portal_date(date(2026, 4, 15)) == "15-04-2026"
        assert filing_service.to_portal_date(None) is None


class TestARecordedFilingCarriesWhatThatReturnDeclared:
    """P19 M2: recording a filing stored totals beside the ARN from every sale
    of the period, for both returns. GSTR-1 does list every sale; GSTR-3B's
    3.1(a) leaves out reverse-charge sales (the recipient's tax) and nil-rated
    ones, so a recorded 3B claimed more tax than the document stored next to it
    declared."""

    def _period(self, db_session, business):
        _sale(db_session, business, number="S-1", taxable="10000",
              cgst="900", sgst="900", total="11800")
        _sale(db_session, business, number="S-RCM", taxable="50000",
              cgst="4500", sgst="4500", total="59000", rc=True)

    def test_a_recorded_3b_totals_its_own_3_1_a(self, db_session, business):
        from app.models.gstr_return import ReturnType

        self._period(db_session, business)
        record = filing_service.record_filing(
            db_session, business, PERIOD, ReturnType.GSTR3B, filed_on=date(2026, 5, 18)
        )
        declared = record.data["sup_details"]["osup_det"]
        assert record.total_taxable_value == Decimal("10000.00") == Decimal(str(declared["txval"]))
        assert record.total_cgst == Decimal("900.00")
        assert record.total_sgst == Decimal("900.00")
        assert record.invoice_count == 2

    def test_a_recorded_gstr1_still_totals_every_sale_it_lists(self, db_session, business):
        from app.models.gstr_return import ReturnType

        self._period(db_session, business)
        record = filing_service.record_filing(
            db_session, business, PERIOD, ReturnType.GSTR1, filed_on=date(2026, 5, 10)
        )
        assert record.total_taxable_value == Decimal("60000.00")
        assert record.total_cgst == Decimal("5400.00")
