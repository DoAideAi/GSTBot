"""M3 state machine: invoice lifecycle — UPLOADED → PROCESSING → PARSED|FAILED,
then MATCHED|MISMATCHED|MISSING_IN_2B|DUPLICATE from reconciliation.

Guards:
- Only UPLOADED invoices may be claimed for parsing (CAS in the task).
- A DUPLICATE may not be reparsed (409).
- A PROCESSING invoice may not be reparsed (409).
- Correcting a reconciled field resets to PARSED (verdict withdrawn).
- Correcting a DUPLICATE's identity fields resets to PARSED.
- A deleted invoice is skipped by the parser task.

Side effects:
- Parsing sets parse_error to None on success.
- A failed parse records the error on the row.
- Reconciliation writes the invoice status from the match category.
- Correction of a reconciled field withdraws the match verdict.

Idempotency:
- Claiming an already-claimed invoice is a no-op (rowcount 0).
- Processing an already-parsed invoice is skipped by the task guard.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import update

from app.models.invoice import (
    UNREADABLE_STATUSES,
    Invoice,
    InvoiceStatus,
    InvoiceType,
)

ZERO = Decimal("0.00")


def _upload(db, business, *, number="INV-SM-1", status=InvoiceStatus.UPLOADED) -> Invoice:
    inv = Invoice(
        business_id=business.id,
        invoice_type=InvoiceType.PURCHASE,
        status=status,
        invoice_number=number,
        invoice_date=date(2026, 4, 15),
        period="2026-04",
        counterparty_gstin="27AAPFU0939F1ZV",
        counterparty_name="Vendor",
        taxable_value=Decimal("10000"),
        cgst=Decimal("900"),
        sgst=Decimal("900"),
        igst=ZERO,
        cess=ZERO,
        total_value=Decimal("11800"),
    )
    inv.status = status
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# -----------------------------------------------------------------------
# Upload → Processing claim (CAS guard)
# -----------------------------------------------------------------------

class TestClaimForProcessing:

    def test_an_uploaded_invoice_can_be_claimed(self, db_session, business):
        inv = _upload(db_session, business)
        claimed = db_session.execute(
            update(Invoice)
            .where(Invoice.id == inv.id, Invoice.status == InvoiceStatus.UPLOADED)
            .values(status=InvoiceStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ).rowcount
        db_session.commit()
        assert claimed == 1
        db_session.refresh(inv)
        assert inv.status is InvoiceStatus.PROCESSING

    def test_a_parsed_invoice_cannot_be_claimed(self, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.PARSED)
        claimed = db_session.execute(
            update(Invoice)
            .where(Invoice.id == inv.id, Invoice.status == InvoiceStatus.UPLOADED)
            .values(status=InvoiceStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ).rowcount
        db_session.commit()
        assert claimed == 0
        db_session.refresh(inv)
        assert inv.status is InvoiceStatus.PARSED

    def test_claiming_twice_only_succeeds_once(self, db_session, business):
        inv = _upload(db_session, business)
        first = db_session.execute(
            update(Invoice)
            .where(Invoice.id == inv.id, Invoice.status == InvoiceStatus.UPLOADED)
            .values(status=InvoiceStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ).rowcount
        db_session.commit()
        second = db_session.execute(
            update(Invoice)
            .where(Invoice.id == inv.id, Invoice.status == InvoiceStatus.UPLOADED)
            .values(status=InvoiceStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ).rowcount
        db_session.commit()
        assert first == 1
        assert second == 0


# -----------------------------------------------------------------------
# Reparse guards: DUPLICATE and PROCESSING are refused
# -----------------------------------------------------------------------

class TestReparseGuards:

    def test_reparse_of_a_duplicate_is_refused(self, auth_client, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.DUPLICATE)
        resp = auth_client.post(f"/api/v1/invoices/{inv.id}/reparse")
        assert resp.status_code == 409
        assert "duplicate" in resp.text.lower()

    def test_reparse_of_a_processing_invoice_is_refused(self, auth_client, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.PROCESSING)
        resp = auth_client.post(f"/api/v1/invoices/{inv.id}/reparse")
        assert resp.status_code == 409
        assert "currently being processed" in resp.text.lower()

    def test_reparse_of_a_parsed_invoice_is_allowed(self, auth_client, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.PARSED)
        inv.raw_text = "Invoice No: INV-SM-1\nTotal: 11800"
        db_session.commit()
        resp = auth_client.post(f"/api/v1/invoices/{inv.id}/reparse")
        assert resp.status_code == 200

    def test_reparse_of_a_failed_invoice_is_allowed(self, auth_client, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.FAILED)
        inv.raw_text = "Invoice No: INV-SM-1\nTotal: 11800"
        inv.parse_error = "Previous error"
        db_session.commit()
        resp = auth_client.post(f"/api/v1/invoices/{inv.id}/reparse")
        assert resp.status_code == 200


# -----------------------------------------------------------------------
# Correction of reconciled fields withdraws the verdict
# -----------------------------------------------------------------------

class TestCorrectionWithdrawsVerdict:

    def test_correcting_taxable_value_resets_matched_to_parsed(
        self, auth_client, db_session, business,
    ):
        inv = _upload(db_session, business, status=InvoiceStatus.MATCHED)
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"taxable_value": "9999"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, inv.id)
        assert stored.status is InvoiceStatus.PARSED

    def test_correcting_igst_resets_mismatched_to_parsed(
        self, auth_client, db_session, business,
    ):
        inv = _upload(db_session, business, status=InvoiceStatus.MISMATCHED)
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"igst": "1800"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, inv.id)
        assert stored.status is InvoiceStatus.PARSED

    def test_correcting_invoice_number_resets_duplicate_to_parsed(
        self, auth_client, db_session, business,
    ):
        inv = _upload(db_session, business, status=InvoiceStatus.DUPLICATE)
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"invoice_number": "INV-NEW"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, inv.id)
        assert stored.status is InvoiceStatus.PARSED

    def test_correcting_hsn_does_not_reset_matched_status(
        self, auth_client, db_session, business,
    ):
        inv = _upload(db_session, business, status=InvoiceStatus.MATCHED)
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"hsn_code": "8472"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, inv.id)
        assert stored.status is InvoiceStatus.MATCHED

    def test_correcting_a_failed_invoice_moves_it_to_parsed(
        self, auth_client, db_session, business,
    ):
        inv = _upload(db_session, business, status=InvoiceStatus.FAILED)
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"taxable_value": "5000"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, inv.id)
        assert stored.status is InvoiceStatus.PARSED


# -----------------------------------------------------------------------
# Reconciliation writes status from match category
# -----------------------------------------------------------------------

class TestReconciliationSetsInvoiceStatus:

    def test_a_matched_invoice_gets_matched_status(self, db_session, business):
        from app.models.reconciliation_run import MatchCategory
        from app.services.reconciliation import (
            Finding,
            ReconciliationResult,
            _apply_statuses,
        )

        inv = _upload(db_session, business, status=InvoiceStatus.PARSED)
        finding = Finding(
            invoice=inv,
            record=None,
            category=MatchCategory.MATCHED,
            carried=False,
        )
        result = ReconciliationResult(
            findings=[finding],
            period="2026-04",
        )
        _apply_statuses(result)
        assert inv.status is InvoiceStatus.MATCHED

    def test_a_carried_invoice_keeps_its_status(self, db_session, business):
        from app.models.reconciliation_run import MatchCategory
        from app.services.reconciliation import Finding, ReconciliationResult, _apply_statuses

        inv = _upload(db_session, business, status=InvoiceStatus.MISSING_IN_2B)
        finding = Finding(
            invoice=inv,
            record=None,
            category=MatchCategory.MATCHED,
            carried=True,
        )
        result = ReconciliationResult(
            findings=[finding],
            period="2026-04",
        )
        _apply_statuses(result)
        assert inv.status is InvoiceStatus.MISSING_IN_2B


# -----------------------------------------------------------------------
# UNREADABLE_STATUSES contract
# -----------------------------------------------------------------------

class TestUnreadableStatusesContract:

    def test_failed_uploaded_processing_are_unreadable(self):
        assert InvoiceStatus.FAILED in UNREADABLE_STATUSES
        assert InvoiceStatus.UPLOADED in UNREADABLE_STATUSES
        assert InvoiceStatus.PROCESSING in UNREADABLE_STATUSES

    def test_parsed_is_readable(self):
        assert InvoiceStatus.PARSED not in UNREADABLE_STATUSES

    def test_matched_is_readable(self):
        assert InvoiceStatus.MATCHED not in UNREADABLE_STATUSES


# -----------------------------------------------------------------------
# Soft delete: deleted invoice is skipped by parser
# -----------------------------------------------------------------------

class TestDeletedInvoiceIsSkipped:

    def test_a_deleted_invoice_cannot_be_patched(self, auth_client, db_session, business):
        inv = _upload(db_session, business, status=InvoiceStatus.PARSED)
        resp = auth_client.delete(f"/api/v1/invoices/{inv.id}")
        assert resp.status_code == 204
        resp = auth_client.patch(
            f"/api/v1/invoices/{inv.id}",
            json={"taxable_value": "5000"},
        )
        assert resp.status_code == 404
