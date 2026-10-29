"""Clearing an invoice's date takes it out of the month the date put it in.

``period`` is the month of ``invoice_date`` and nothing else: a row with no
date is in no period, left out of every return, and named by validation as
needing one. Sending ``null`` for the date is the documented way to take a
misread one back off an invoice, but the edit re-derived the period only when
the new date was truthy — so the row kept the misread month. It went on being
declared in that month's returns with no date at all, and validation, which
looks for rows with no period, never asked for one.
"""
from __future__ import annotations

from tests.conftest import make_paid

INVOICE = "Invoice No: INV-7\nDate: 01/04/2026\nTaxable Value: 1000\nIGST: 180\nTotal: 1180\n"


def _dated_sale(auth_client) -> int:
    upload = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("sale.txt", INVOICE.encode(), "text/plain")},
        data={"invoice_type": "sales"},
    )
    assert upload.status_code in (200, 201), upload.text
    invoice_id = upload.json()["invoice"]["id"]
    dated = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={
        "invoice_date": "2026-04-01", "taxable_value": "1000", "igst": "180",
        "cgst": "0", "sgst": "0", "total_value": "1180",
        "counterparty_gstin": "29AAGCR4375J1ZU", "place_of_supply": "29", "tax_rate": "18",
    })
    assert dated.status_code == 200, dated.text
    assert dated.json()["period"] == "2026-04"
    return invoice_id


def test_a_cleared_date_leaves_the_invoice_in_no_period(auth_client, db_session, business):
    make_paid(db_session, business.id)
    invoice_id = _dated_sale(auth_client)

    cleared = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"invoice_date": None})

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["invoice_date"] is None
    assert cleared.json()["period"] is None


def test_the_month_it_left_no_longer_declares_it(auth_client, db_session, business):
    from app.services import invoice_service

    make_paid(db_session, business.id)
    invoice_id = _dated_sale(auth_client)
    assert invoice_service.tax_summary(db_session, business.id, "2026-04")["sales"]["count"] == 1

    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"invoice_date": None})

    db_session.expire_all()
    april = invoice_service.tax_summary(db_session, business.id, "2026-04")["sales"]
    assert april["count"] == 0
    assert april["igst"] == 0
