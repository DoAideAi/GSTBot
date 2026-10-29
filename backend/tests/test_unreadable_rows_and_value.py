"""Three ways a row that has not been read, or a total that was never printed,
reached a figure a business acts on.

The three are separate defects with one shape in common: some part of the
product answered a question about money from a different set of rows, or a
different column, than the return it sits beside does. Each of them left two
numbers on screen that describe the same thing and disagree, with nothing to say
which one is wrong.

1. :func:`~app.services.invoice_service.tax_summary` excluded ``FAILED`` alone
   where every other money path excludes
   :data:`~app.models.invoice.UNREADABLE_STATUSES`.
2. :attr:`~app.models.invoice.Invoice.invoice_value` did not exist, so the
   screens read a ``total_value`` column that is zero whenever the extractor
   found no grand-total *label* — while every export derived the real figure.
3. The heuristic reverse-charge reader could only ever answer yes, because the
   label word "Applicable" satisfied the pattern's affirmative.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from app.models.gstr_return import ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import filing as filing_service
from app.services import gst_calendar, invoice_parser, invoice_service
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE

PERIOD = "2026-04"


def sale(db, business_id, *, number, status=InvoiceStatus.PARSED, taxable="10000.00",
         igst="1800.00", total=None) -> Invoice:
    taxable_value = Decimal(taxable)
    tax = Decimal(igst)
    invoice = Invoice(
        business_id=business_id,
        invoice_type=InvoiceType.SALES,
        status=status,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number=number,
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        place_of_supply="29",
        hsn_code="84713010",
        taxable_value=taxable_value,
        igst=tax,
        total_value=Decimal(total) if total is not None else taxable_value + tax,
    )
    db.add(invoice)
    db.commit()
    return invoice


# ---------------------------------------------------------------------------
# 1. A row the return leaves out must not be in the totals recorded beside it
# ---------------------------------------------------------------------------

class TestRowsNothingHasRead:
    """The period summary counts what the return contains, and nothing else.

    A re-extraction is the case that costs money rather than merely looking
    untidy: ``process_invoice`` writes ``PROCESSING`` and commits before it
    reads anything, so the figures from the last successful read stay on the
    row for the length of the parse. The returns skip it; the summary did not.
    """

    def test_a_row_being_re_extracted_is_out_of_the_period_summary(
        self, db_session, business
    ):
        sale(db_session, business.id, number="S-1")
        # Same shape, mid-re-parse, still carrying the previous read's figures.
        sale(
            db_session,
            business.id,
            number="S-2",
            status=InvoiceStatus.PROCESSING,
            taxable="50000.00",
            igst="9000.00",
        )

        summary = invoice_service.tax_summary(db_session, business.id, PERIOD)["sales"]

        assert summary["count"] == 1
        assert summary["taxable_value"] == Decimal("10000.00")
        assert summary["igst"] == Decimal("1800.00")

    def test_a_row_still_queued_for_a_worker_is_out_of_it_too(self, db_session, business):
        sale(db_session, business.id, number="S-1")
        sale(db_session, business.id, number="S-2", status=InvoiceStatus.UPLOADED)

        summary = invoice_service.tax_summary(db_session, business.id, PERIOD)["sales"]

        assert summary["count"] == 1

    def test_the_summary_and_the_return_agree_about_the_period(self, db_session, business):
        """The two answers a filing is recorded from, side by side."""
        sale(db_session, business.id, number="S-1")
        sale(
            db_session,
            business.id,
            number="S-2",
            status=InvoiceStatus.PROCESSING,
            taxable="50000.00",
            igst="9000.00",
        )

        document = filing_service.build_gstr1(db_session, business, PERIOD)
        in_document = sum(len(entry["inv"]) for entry in document.get("b2b", []))
        summary = invoice_service.tax_summary(db_session, business.id, PERIOD)["sales"]

        assert in_document == summary["count"] == 1

    def test_a_recorded_filing_stores_the_totals_of_the_return_it_stores(
        self, db_session, business, monkeypatch
    ):
        """The row an assessment is answered from cannot contradict itself.

        ``record_filing`` writes the summary's totals onto the same row as the
        document ``build_gstr1`` produced. Read from two different sets of rows,
        the stored taxable value was one the stored return does not contain.
        """
        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 6, 15))
        sale(db_session, business.id, number="S-1")
        sale(
            db_session,
            business.id,
            number="S-2",
            status=InvoiceStatus.PROCESSING,
            taxable="50000.00",
            igst="9000.00",
        )

        record = filing_service.record_filing(
            db_session, business, PERIOD, ReturnType.GSTR1, arn="AA270426000000X"
        )

        declared = sum(
            item["itm_det"]["txval"]
            for entry in record.data.get("b2b", [])
            for invoice in entry["inv"]
            for item in invoice["itms"]
        )
        assert record.invoice_count == 1
        assert record.total_taxable_value == Decimal("10000.00")
        assert Decimal(str(declared)) == record.total_taxable_value

    def test_a_failed_row_is_still_excluded(self, db_session, business):
        """The narrower rule this replaces was not wrong, only incomplete."""
        sale(db_session, business.id, number="S-1")
        sale(db_session, business.id, number="S-2", status=InvoiceStatus.FAILED)

        assert invoice_service.tax_summary(db_session, business.id, PERIOD)["sales"]["count"] == 1

    def test_a_matched_row_is_not_excluded(self, db_session, business):
        """Reconciliation statuses are read rows, and stay in the totals."""
        sale(db_session, business.id, number="S-1", status=InvoiceStatus.MATCHED)

        summary = invoice_service.tax_summary(db_session, business.id, PERIOD)["sales"]
        assert summary["count"] == 1
        assert summary["igst"] == Decimal("1800.00")


# ---------------------------------------------------------------------------
# 2. What an invoice is worth, when nothing printed the word "total"
# ---------------------------------------------------------------------------

class TestWhatAnInvoiceIsWorth:
    """A stored zero total is a label the parser did not find, not a nil supply."""

    def test_a_total_that_was_never_extracted_is_derived(self, db_session, business):
        invoice = sale(db_session, business.id, number="S-1", total="0.00")

        assert invoice.total_value == Decimal("0.00")
        assert invoice.invoice_value == Decimal("11800.00")

    def test_a_stored_total_is_preferred_to_a_derived_one(self, db_session, business):
        """Including a wrong one: validation is what says a total does not foot."""
        invoice = sale(db_session, business.id, number="S-1", total="11801.00")

        assert invoice.invoice_value == Decimal("11801.00")

    def test_the_api_serves_the_figure_the_return_uses(self, auth_client, db_session, business):
        invoice = sale(db_session, business.id, number="S-1", total="0.00")

        body = auth_client.get(f"/api/v1/invoices/{invoice.id}").json()

        # The raw column stays as extracted — it is what a reviewer edits.
        assert Decimal(body["total_value"]) == Decimal("0.00")
        assert Decimal(body["invoice_value"]) == Decimal("11800.00")

    def test_the_list_carries_it_too(self, auth_client, db_session, business):
        sale(db_session, business.id, number="S-1", total="0.00")

        items = auth_client.get("/api/v1/invoices").json()["items"]

        assert [Decimal(item["invoice_value"]) for item in items] == [Decimal("11800.00")]

    def test_the_register_and_the_return_value_one_invoice_the_same(
        self, auth_client, db_session, business
    ):
        """The disagreement this exists to close, asserted end to end."""
        invoice = sale(db_session, business.id, number="S-1", total="0.00")

        shown = Decimal(auth_client.get(f"/api/v1/invoices/{invoice.id}").json()["invoice_value"])
        document = filing_service.build_gstr1(db_session, business, PERIOD)
        filed = Decimal(str(document["b2b"][0]["inv"][0]["val"]))

        assert shown == filed == Decimal("11800.00")

    def test_an_unrecognised_total_label_is_what_produces_the_zero(self):
        """Why the column cannot simply be trusted, from the parser's end.

        ``_TOTAL_PATTERN`` knows a fixed vocabulary — "Grand Total", "Total
        Value", "Amount Payable", "Net Payable" and a bare "Total" among them —
        and a wording outside it, such as "Total Payable", leaves the column at
        zero with every other figure on the invoice correct. See
        ``tests/test_invoice_formats.py`` for the corpus this vocabulary is
        checked against; this test is only about what a *miss* does to the
        figure the rest of this module reasons about.
        """
        parsed = invoice_parser.parse_heuristic(
            "Invoice No: INV-1\n"
            "Invoice Date: 15/04/2026\n"
            "Taxable Value: 450000.00\n"
            "IGST @ 18%: 81000.00\n"
            "Total Payable: 531000.00\n"
        )

        assert parsed.taxable_value == Decimal("450000.00")
        assert parsed.total_value == Decimal("0.00")


# ---------------------------------------------------------------------------
# 3. Reading rule 46(p)'s answer off the face of the invoice
# ---------------------------------------------------------------------------

class TestReverseChargeOnTheDocument:
    """The label and the answer overlap, and only the answer decides.

    A false yes moves the tax into GSTR-3B 3.1(d) as cash the business must
    find, drops the invoice's credit, and on a sale tells the customer they owe
    tax already charged to them. A false no leaves a real liability undeclared.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "Reverse Charge Applicable: No",
            "Whether Reverse Charge Applicable: No",
            "Reverse Charge Applicable : N",
            "Reverse charge applicable  No",
            "Reverse Charge is applicable: No",
            "Reverse Charge: Not Applicable",
            "Reverse Charge: N/A",
            "Reverse Charge (Y/N): N",
            "Whether tax payable on reverse charge basis: No",
        ],
    )
    def test_an_invoice_that_says_no_is_not_reverse_charge(self, line):
        parsed = invoice_parser.parse_heuristic(f"Invoice No: A-1\n{line}\n")

        assert parsed.reverse_charge is False

    @pytest.mark.parametrize(
        "line",
        [
            "Reverse Charge: Yes",
            "Reverse Charge: Y",
            "Reverse Charge Applicable: Yes",
            "Reverse Charge (Y/N): Y",
            "Reverse Charge: Applicable",
            "Whether tax payable on reverse charge basis: Yes",
        ],
    )
    def test_an_invoice_that_says_yes_is(self, line):
        parsed = invoice_parser.parse_heuristic(f"Invoice No: A-1\n{line}\n")

        assert parsed.reverse_charge is True

    def test_an_unanswered_label_is_not_a_declaration(self):
        """A heading with nothing after it says nothing, and must not guess.

        This is where the old pattern's backtracking left it: unable to match an
        answer, it gave the label word back and read "Applicable" as one.
        """
        parsed = invoice_parser.parse_heuristic("Invoice No: A-1\nREVERSE CHARGE APPLICABLE\n")

        assert parsed.reverse_charge is False

    def test_an_invoice_that_does_not_mention_it_is_not_reverse_charge(self):
        parsed = invoice_parser.parse_heuristic("Invoice No: A-1\nTaxable Value: 100.00\n")

        assert parsed.reverse_charge is False

    def test_the_flag_survives_into_the_return_it_changes(self, db_session, business):
        """What the misreading actually cost: ``rchrg`` in a customer's 2B."""
        invoice = sale(db_session, business.id, number="S-1")
        parsed = invoice_parser.parse_heuristic(
            "Invoice No: S-1\nReverse Charge Applicable: No\n"
        )
        invoice.reverse_charge = parsed.reverse_charge
        db_session.commit()

        document = filing_service.build_gstr1(db_session, business, PERIOD)

        assert document["b2b"][0]["inv"][0]["rchrg"] == "N"

    def test_a_purchase_that_says_no_keeps_its_credit(self, db_session, business):
        """And what it cost on the buying side: the credit leaves the pool.

        A reverse-charge purchase is excluded from ``available`` outright, so
        one misread label is the whole of that invoice's credit.
        """
        from app.services import itc as itc_service

        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PARSED,
                counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
                invoice_number="P-1",
                invoice_date=date(2026, 4, 10),
                period=PERIOD,
                taxable_value=Decimal("100000.00"),
                cgst=Decimal("9000.00"),
                sgst=Decimal("9000.00"),
                total_value=Decimal("118000.00"),
                reverse_charge=invoice_parser.parse_heuristic(
                    "Invoice No: P-1\nReverse Charge Applicable: No\n"
                ).reverse_charge,
            )
        )
        db_session.commit()

        summary = itc_service.summarise(db_session, business.id, PERIOD)

        assert summary.available.total == Decimal("18000.00")
        assert summary.reverse_charge.invoice_count == 0


# ---------------------------------------------------------------------------
# A row with no period is not missing from every period's validation
# ---------------------------------------------------------------------------

class TestRowsWithNoPeriod:
    """A row's period comes from a date the extraction read.

    A fresh upload, a failed extraction and a parse that found no date all sit
    at ``period IS NULL``, and validation selected by ``period ==``. A month
    whose only failed sales extraction was its first parse came back ``ok``,
    with that supply missing from the GSTR-1.
    """

    def _undated(self, db, business, *, status, uploaded_on, number="S-ND-1"):
        invoice = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=status,
            invoice_number=number,
            taxable_value=Decimal("10000.00"),
            igst=Decimal("1800.00"),
            total_value=Decimal("11800.00"),
            parse_error="unreadable scan" if status is InvoiceStatus.FAILED else None,
            created_at=datetime.combine(uploaded_on, time(12), tzinfo=UTC),
        )
        db.add(invoice)
        db.commit()
        return invoice

    def _issues(self, db, business, period=PERIOD):
        report = filing_service.validate_period(db, business, period)
        return report, {issue.invoice_id: issue for issue in report.issues}

    @pytest.mark.parametrize(
        "status", [InvoiceStatus.FAILED, InvoiceStatus.UPLOADED, InvoiceStatus.PROCESSING]
    )
    def test_an_unread_upload_blocks_the_month_it_arrived_in(self, db_session, business, status):
        row = self._undated(db_session, business, status=status, uploaded_on=date(2026, 4, 20))
        report, issues = self._issues(db_session, business)
        assert not report.ok
        assert issues[row.id].field == "status"

    def test_october_bills_uploaded_in_november_block_october(self, db_session, business):
        # The usual order: a month's invoices arrive after it ends, before the 11th.
        row = self._undated(
            db_session, business, status=InvoiceStatus.FAILED, uploaded_on=date(2026, 5, 2)
        )
        report, issues = self._issues(db_session, business)
        assert not report.ok and row.id in issues

    def test_a_month_that_began_after_the_upload_is_not_blocked(self, db_session, business):
        self._undated(
            db_session, business, status=InvoiceStatus.FAILED, uploaded_on=date(2026, 3, 30)
        )
        report, _ = self._issues(db_session, business)
        assert report.ok

    def test_a_read_invoice_with_no_date_says_to_enter_the_date(self, db_session, business):
        row = self._undated(
            db_session, business, status=InvoiceStatus.PARSED, uploaded_on=date(2026, 4, 20)
        )
        report, issues = self._issues(db_session, business)
        assert not report.ok
        assert "Enter its date" in issues[row.id].message

    def test_through_the_api(self, auth_client, db_session, business):
        self._undated(
            db_session, business, status=InvoiceStatus.FAILED, uploaded_on=date(2026, 4, 20)
        )
        body = auth_client.get(f"/api/v1/filing/validate?period={PERIOD}").json()
        assert body["ok"] is False
        assert "unreadable scan" in body["issues"][0]["message"]

    def test_a_dated_row_of_another_month_is_still_not_named(self, db_session, business):
        other = sale(db_session, business.id, number="S-MAY", status=InvoiceStatus.FAILED)
        other.period = "2026-05"
        db_session.commit()
        report, _ = self._issues(db_session, business)
        assert report.ok
