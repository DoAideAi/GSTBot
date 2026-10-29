"""A DUPLICATE invoice must stay DUPLICATE unless its identity changes.

Reconciliation marks an invoice DUPLICATE when a normalized match finds
another row for the same counterparty and invoice number.  That verdict is
about who the supplier is and what number they gave it, not about the money
on the row.  Two paths used to silently un-duplicate an invoice, putting it
back into the filing pool where the supply was counted twice:

1. ``POST /{id}/reparse`` — re-runs extraction, blindly sets PROCESSING then
   PARSED. The database constraint only catches *exact* key collisions, not
   the normalised match reconciliation uses, so the row escapes.

2. ``PATCH /{id}`` with a money field — the withdrawal logic treated
   DUPLICATE like any other reconciliation verdict, withdrawing it to PARSED
   whenever a reconciled field changed. But the duplicate condition is about
   counterparty + number, not about money: editing ``taxable_value`` should
   not un-duplicate the row.

Both are now guarded.
"""
from __future__ import annotations

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


def _invoice_text(number: str = "DUP-001") -> str:
    return f"""\
NORTHWIND SUPPLIES PRIVATE LIMITED
GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}
1st Floor, MG Road, Bengaluru, Karnataka 560001

TAX INVOICE

Invoice No: {number}
Invoice Date: 15/04/2026
Place of Supply: 27 Maharashtra

Bill To:
UMANG TRADERS
GSTIN: {BUSINESS_GSTIN}

HSN Code: 84713010
Taxable Value:  100000.00
IGST @ 18%:      18000.00
Grand Total:    118000.00
"""


def _upload(client, text: str, *, name: str = "dup.txt"):
    return client.post(
        "/api/v1/invoices/upload",
        files={"file": (name, text.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
    )


@pytest.fixture()
def duplicate_invoice(auth_client, db_session, business):
    """A parsed invoice manually set to DUPLICATE, the way reconciliation does."""
    resp = _upload(auth_client, _invoice_text(), name="dup-original.txt")
    assert resp.status_code == 201, resp.text
    inv_id = resp.json()["invoice"]["id"]
    inv = db_session.get(Invoice, inv_id)
    inv.status = InvoiceStatus.DUPLICATE
    db_session.commit()
    db_session.refresh(inv)
    return inv


class TestReparseRefusesDuplicate:
    def test_reparse_on_a_duplicate_invoice_is_refused(self, auth_client, duplicate_invoice):
        resp = auth_client.post(f"/api/v1/invoices/{duplicate_invoice.id}/reparse")
        assert resp.status_code == 409

    def test_the_status_stays_duplicate(self, auth_client, db_session, duplicate_invoice):
        auth_client.post(f"/api/v1/invoices/{duplicate_invoice.id}/reparse")
        db_session.refresh(duplicate_invoice)
        assert duplicate_invoice.status == InvoiceStatus.DUPLICATE


class TestPatchMoneyFieldDoesNotUnDuplicate:
    def test_patching_taxable_value_keeps_duplicate(
        self, auth_client, db_session, duplicate_invoice,
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{duplicate_invoice.id}",
            json={"taxable_value": "200000.00"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == InvoiceStatus.DUPLICATE.value

    def test_patching_igst_keeps_duplicate(self, auth_client, db_session, duplicate_invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{duplicate_invoice.id}",
            json={"igst": "36000.00"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == InvoiceStatus.DUPLICATE.value

    def test_patching_invoice_date_keeps_duplicate(
        self, auth_client, db_session, duplicate_invoice,
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{duplicate_invoice.id}",
            json={"invoice_date": "2026-05-01"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == InvoiceStatus.DUPLICATE.value


class TestPatchIdentityFieldWithdrawsDuplicate:
    def test_patching_invoice_number_withdraws_duplicate(
        self, auth_client, db_session, duplicate_invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{duplicate_invoice.id}",
            json={"invoice_number": "UNIQUE-999"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == InvoiceStatus.PARSED.value

    def test_patching_counterparty_gstin_withdraws_duplicate(
        self, auth_client, db_session, duplicate_invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{duplicate_invoice.id}",
            json={"counterparty_gstin": SUPPLIER_GSTIN_SAME_STATE},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == InvoiceStatus.PARSED.value


class TestTheSameNumberInAnotherCaseIsTheSameInvoice:
    """P39 M12: "INV-1" and "inv-1" from one supplier were two invoices.

    A supplier's invoice number is unique within a financial year (Rule 46),
    whatever its case. The guard against booking a document twice was the
    unique index on (business, type, supplier GSTIN, number), which compares
    the number exactly as typed, and the sales check compared it the same way.
    The same purchase scanned once from a PDF and once typed in lower case was
    stored twice, and the ITC summary claimed its credit twice until a
    reconciliation happened to mark one a duplicate. A number that differs
    only in case is now the invoice already on file, at every door.
    """

    def _sale_text(self, number):
        return _invoice_text(number).replace(
            f"GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}", f"GSTIN: {BUSINESS_GSTIN}", 1
        ).replace(f"Bill To:\nUMANG TRADERS\nGSTIN: {BUSINESS_GSTIN}",
                  f"Bill To:\nACME\nGSTIN: {SUPPLIER_GSTIN_SAME_STATE}")

    def test_a_purchase_repeated_in_another_case_is_refused(self, auth_client, db_session):
        first = _upload(auth_client, _invoice_text("INV-2026-0042"), name="a.txt")
        again = _upload(auth_client, _invoice_text("inv-2026-0042"), name="b.txt")

        assert first.json()["invoice"]["status"] == "parsed"
        repeat = db_session.get(Invoice, again.json()["invoice"]["id"])
        assert repeat.status is InvoiceStatus.FAILED
        assert "already on file" in (repeat.parse_error or "")

    def test_its_credit_is_claimed_once(self, auth_client, paid_business):
        _upload(auth_client, _invoice_text("INV-2026-0042"), name="a.txt")
        _upload(auth_client, _invoice_text("inv-2026-0042"), name="b.txt")

        itc = auth_client.get("/api/v1/itc?period=2026-04").json()
        assert itc["available"]["igst"] == "18000.00"

    def test_a_sale_repeated_in_another_case_is_refused(self, auth_client, db_session):
        first = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("s1.txt", self._sale_text("S-77").encode(), "text/plain")},
            data={"invoice_type": "sales"},
        )
        again = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("s2.txt", self._sale_text("s-77").encode(), "text/plain")},
            data={"invoice_type": "sales"},
        )
        assert first.json()["invoice"]["status"] != "failed"
        repeat = db_session.get(Invoice, again.json()["invoice"]["id"])
        assert repeat.status is InvoiceStatus.FAILED

    def test_a_correction_onto_another_invoice_in_another_case_is_refused(self, auth_client):
        _upload(auth_client, _invoice_text("INV-1"), name="a.txt")
        other = _upload(auth_client, _invoice_text("INV-2"), name="b.txt").json()["invoice"]["id"]

        response = auth_client.patch(f"/api/v1/invoices/{other}", json={"invoice_number": "inv-1"})
        assert response.status_code == 409

    def test_correcting_only_the_case_of_its_own_number_is_allowed(self, auth_client):
        mine = _upload(auth_client, _invoice_text("INV-9"), name="a.txt").json()["invoice"]["id"]

        response = auth_client.patch(f"/api/v1/invoices/{mine}", json={"invoice_number": "inv-9"})
        assert response.status_code == 200, response.text
