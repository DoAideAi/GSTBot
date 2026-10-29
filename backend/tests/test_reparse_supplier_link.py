"""A purchase's supplier link follows the GSTIN it was last read with.

``apply_parsed`` linked a purchase to a supplier when an extraction found a
GSTIN, and never unlinked it: a re-read that found none left the row saying
"no counterparty GSTIN" while still pointing at the old supplier — in the API
response and in the account export. The edit route already clears the link
when a correction clears the GSTIN; the parse path now agrees with it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.supplier import Supplier
from app.services import invoice_service
from app.services.invoice_parser import ParsedInvoice
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


def _purchase(supplier_gstin):
    return ParsedInvoice(
        supplier_gstin=supplier_gstin, supplier_name="Vendor",
        buyer_gstin=BUSINESS_GSTIN, invoice_number="P-7", invoice_date=date(2026, 4, 10),
        taxable_value=Decimal("100.00"), igst=Decimal("18.00"),
        total_value=Decimal("118.00"), raw_text="scan",
    )


@pytest.fixture()
def reread(db_session, business, monkeypatch):
    row = Invoice(business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                  status=InvoiceStatus.UPLOADED, raw_text="scan")
    db_session.add(row)
    db_session.commit()

    def run(gstin):
        monkeypatch.setattr(invoice_service, "parse_invoice", lambda **_: _purchase(gstin))
        return invoice_service.process_invoice(db_session, row, business_gstin=BUSINESS_GSTIN)

    return run


def _supplier_id(db, gstin):
    return db.query(Supplier).filter_by(gstin=gstin).one().id


def test_a_reread_that_finds_no_gstin_unlinks_the_supplier(reread, db_session):
    first = reread(SUPPLIER_GSTIN_OTHER_STATE)
    assert first.supplier_id == _supplier_id(db_session, SUPPLIER_GSTIN_OTHER_STATE)

    again = reread(None)

    assert again.counterparty_gstin is None
    assert again.supplier_id is None


def test_a_reread_that_finds_another_gstin_moves_the_link(reread, db_session):
    reread(SUPPLIER_GSTIN_OTHER_STATE)
    again = reread(SUPPLIER_GSTIN_SAME_STATE)
    assert again.supplier_id == _supplier_id(db_session, SUPPLIER_GSTIN_SAME_STATE)


def test_the_api_says_the_same_as_the_row(reread, auth_client):
    reread(SUPPLIER_GSTIN_OTHER_STATE)
    row = reread(None)
    body = auth_client.get(f"/api/v1/invoices/{row.id}").json()
    assert body["counterparty_gstin"] is None and body["supplier_id"] is None
