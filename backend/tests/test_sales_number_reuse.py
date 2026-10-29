"""A sales invoice number is the seller's, once a financial year.

Rule 46 makes a supplier's invoice number unique within a financial year. The
only guard was the unique index on (business, type, counterparty GSTIN,
number), and NULLs never collide in a unique index: a sale to an unregistered
buyer — B2C, no GSTIN — uploaded twice (a second scan of the same paper, so a
different file hash) parsed twice, and GSTR-1 declared it twice. The same
number billed to a different buyer GSTIN slipped past the index the same way.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import filing, invoice_service
from app.services.invoice_parser import ParsedInvoice
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


def _sale(number, when, buyer=None, total="1180.00"):
    return ParsedInvoice(
        supplier_gstin=BUSINESS_GSTIN, supplier_name="Us",
        buyer_gstin=buyer, buyer_name="Walk-in customer",
        invoice_number=number, invoice_date=when, place_of_supply="27",
        taxable_value=Decimal("1000.00"), cgst=Decimal("90.00"), sgst=Decimal("90.00"),
        total_value=Decimal(total), tax_rate=Decimal("18"), raw_text="scan",
    )


@pytest.fixture()
def process(db_session, business, monkeypatch):
    def run(parsed, invoice_type=InvoiceType.SALES):
        row = Invoice(business_id=business.id, invoice_type=invoice_type,
                      status=InvoiceStatus.UPLOADED, raw_text="scan")
        db_session.add(row)
        db_session.commit()
        monkeypatch.setattr(invoice_service, "parse_invoice", lambda **_: parsed)
        return invoice_service.process_invoice(db_session, row, business_gstin=BUSINESS_GSTIN)
    return run


def test_a_second_scan_of_a_b2c_sale_is_a_duplicate(process, db_session, business):
    first = process(_sale("S-101", date(2026, 4, 10)))
    second = process(_sale("S-101", date(2026, 4, 10)))

    assert first.status is InvoiceStatus.PARSED
    assert second.status is InvoiceStatus.FAILED
    assert f"already on file as invoice {first.id}" in second.parse_error

    gstr1 = filing.build_gstr1(db_session, business, "2026-04")
    b2cs = gstr1.get("b2cs") or []
    assert sum(Decimal(str(row["txval"])) for row in b2cs) == Decimal("1000.00")


def test_the_same_number_to_another_buyer_is_a_duplicate(process):
    process(_sale("S-102", date(2026, 4, 10), buyer=SUPPLIER_GSTIN_OTHER_STATE))
    again = process(_sale("S-102", date(2026, 4, 12), buyer=SUPPLIER_GSTIN_SAME_STATE))
    assert again.status is InvoiceStatus.FAILED


def test_numbering_may_restart_in_a_new_financial_year(process):
    process(_sale("S-001", date(2026, 3, 30)))  # FY 2025-26
    next_year = process(_sale("S-001", date(2026, 4, 2)))  # FY 2026-27
    assert next_year.status is InvoiceStatus.PARSED


def test_two_suppliers_may_both_send_number_one(process):
    # Purchases: the number is each supplier's own. Without a GSTIN there is
    # no telling two unregistered suppliers apart, so nothing is refused.
    def purchase(number):
        return ParsedInvoice(
            supplier_gstin=None, supplier_name="Some shop", buyer_gstin=BUSINESS_GSTIN,
            invoice_number=number, invoice_date=date(2026, 4, 10),
            taxable_value=Decimal("100.00"), total_value=Decimal("118.00"), raw_text="scan",
        )
    process(purchase("1"), InvoiceType.PURCHASE)
    again = process(purchase("1"), InvoiceType.PURCHASE)
    assert again.status is InvoiceStatus.PARSED


def test_a_deleted_sale_frees_its_number(process, db_session):
    first = process(_sale("S-103", date(2026, 4, 10)))
    first.soft_delete()
    db_session.commit()
    assert process(_sale("S-103", date(2026, 4, 10))).status is InvoiceStatus.PARSED


def test_an_edit_onto_another_sales_number_is_refused(auth_client, process):
    process(_sale("S-201", date(2026, 4, 10)))
    other = process(_sale("S-202", date(2026, 4, 11)))
    response = auth_client.patch(f"/api/v1/invoices/{other.id}", json={"invoice_number": "S-201"})
    assert response.status_code == 409, response.text
    assert "S-201" in response.json()["detail"]["message"]
