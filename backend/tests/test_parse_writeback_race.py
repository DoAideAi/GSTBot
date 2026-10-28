"""A parse that finishes after something else has already decided the row.

The extraction runs with no lock held, for as long as the model takes, and the
row can move underneath it: an edit (the documented way out of a spinner)
records the user's figures as ``manual``, and a delete removes the invoice. The
write-back used to land regardless, replacing the correction with the very
extraction it corrected, or a ``failed`` verdict over a row the user had fixed.

SQLite ignores ``FOR UPDATE``, so the interleaving is staged by a parser that
performs the concurrent write itself before returning, which is exactly the
state a Postgres worker sees once it takes the lock.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.models.invoice import Invoice, InvoiceStatus
from app.services import invoice_service


def upload(client, text: str) -> int:
    response = client.post(
        "/api/v1/invoices/upload",
        files={"file": ("invoice.txt", text.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
    )
    assert response.status_code == 201, response.text
    return response.json()["invoice"]["id"]


@pytest.fixture()
def invoice_id(auth_client, sample_invoice_text):
    return upload(auth_client, sample_invoice_text)


def _meanwhile(monkeypatch, db, invoice_id, *, raises=False, **values):
    """Make the parser's run overlap a write of *values* to the row."""
    real = invoice_service.parse_invoice

    def parse(**kwargs):
        parsed = real(**kwargs)
        db.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if raises:
            raise RuntimeError("model timed out")
        return parsed

    monkeypatch.setattr(invoice_service, "parse_invoice", parse)


class TestAnEditDuringTheParse:
    CORRECTION = dict(
        status=InvoiceStatus.PARSED,
        taxable_value=Decimal("999.00"),
        parsed_with="manual",
        extraction_confidence=1.0,
    )

    def test_the_correction_survives_the_extraction(self, monkeypatch, db_session, invoice_id):
        _meanwhile(monkeypatch, db_session, invoice_id, **self.CORRECTION)

        invoice = invoice_service.process_invoice(db_session, db_session.get(Invoice, invoice_id))

        assert invoice.parsed_with == "manual"
        assert invoice.extraction_confidence == 1.0
        assert invoice.taxable_value == Decimal("999.00")
        assert invoice.status is InvoiceStatus.PARSED

    def test_a_failing_parse_does_not_mark_the_corrected_row_failed(
        self, monkeypatch, db_session, invoice_id
    ):
        _meanwhile(monkeypatch, db_session, invoice_id, raises=True, **self.CORRECTION)

        invoice = invoice_service.process_invoice(db_session, db_session.get(Invoice, invoice_id))

        assert invoice.status is InvoiceStatus.PARSED
        assert invoice.parse_error is None
        assert invoice.taxable_value == Decimal("999.00")

    def test_without_a_concurrent_write_the_extraction_still_lands(
        self, db_session, invoice_id
    ):
        invoice = db_session.get(Invoice, invoice_id)
        invoice.parsed_with = "manual"
        db_session.commit()

        invoice = invoice_service.process_invoice(db_session, invoice)

        assert invoice.status is InvoiceStatus.PARSED
        assert invoice.parsed_with != "manual"


class TestADeleteDuringTheParse:
    def test_the_deleted_row_is_not_written_back(self, monkeypatch, db_session, invoice_id):
        deleted_at = datetime.now(UTC)
        _meanwhile(monkeypatch, db_session, invoice_id, deleted_at=deleted_at,
                   taxable_value=Decimal("1.00"))

        invoice = invoice_service.process_invoice(db_session, db_session.get(Invoice, invoice_id))

        assert invoice.deleted_at is not None
        assert invoice.taxable_value == Decimal("1.00")


class TestTheWriteBackLocksTheRow:
    def test_the_ownership_check_is_a_for_update(self, monkeypatch, db_session, invoice_id):
        statements = []
        real_execute = db_session.execute

        def spy(statement, *args, **kwargs):
            statements.append(statement)
            return real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "execute", spy)
        invoice_service.process_invoice(db_session, db_session.get(Invoice, invoice_id))

        locking = [s for s in statements if getattr(s, "_for_update_arg", None) is not None]
        assert locking, "the write-back must lock the row it checks"
