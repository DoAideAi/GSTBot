"""Two uploads into one tenant at the same moment.

Both refusals an upload can meet — the plan allowance and the duplicate file —
are a read followed by a write, with no constraint behind either. Two requests
in flight both read "under the limit" and "not on file" and both insert. The
fix is a per-tenant advisory lock taken before either read and released by the
commit that records the row (or the rollback that refuses it).

SQLite has one writer and no advisory locks, so the race itself cannot be
reproduced here. What is pinned instead is the contract the lock depends on:
it is taken first, it is the Postgres lock the comment names, and nothing that
refuses a file leaves it held.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.invoice import InvoiceType
from app.services import invoice_service


@pytest.fixture(autouse=True)
def _upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "invoices"))


def _create(db, business, content=b"a bill"):
    return invoice_service.create_pending_invoice(
        db,
        invoice_service.TenantSnapshot.of(business),
        content=content,
        filename="bill.txt",
        content_type="text/plain",
        invoice_type=InvoiceType.PURCHASE,
    )


class TestTheUploadLock:
    def test_it_is_taken_before_either_check_reads(self, monkeypatch, db_session, business):
        order = []
        monkeypatch.setattr(
            invoice_service, "_serialise_uploads", lambda db, bid: order.append(("lock", bid))
        )
        real_limit, real_dup = invoice_service.check_plan_limit, invoice_service.find_duplicate
        monkeypatch.setattr(
            invoice_service, "check_plan_limit",
            lambda *a, **kw: (order.append("limit"), real_limit(*a, **kw))[1],
        )
        monkeypatch.setattr(
            invoice_service, "find_duplicate",
            lambda *a, **kw: (order.append("duplicate"), real_dup(*a, **kw))[1],
        )

        _create(db_session, business)

        assert order == [("lock", business.id), "limit", "duplicate"]

    def test_on_postgres_it_is_the_transaction_scoped_advisory_lock(self):
        executed = []
        fake = SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=executed.append,
        )

        invoice_service._serialise_uploads(fake, 42)

        [statement] = executed
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "pg_advisory_xact_lock(42, 0)" in sql

    def test_its_key_cannot_meet_a_reconciliation_claim(self):
        # Reconciliation claims (business, YYYYMM); a period is never 0.
        assert invoice_service._UPLOAD_LOCK_KEY == 0

    def test_sqlite_takes_no_lock(self, db_session):
        assert invoice_service._serialise_uploads(db_session, 1) is None

    def test_a_refused_duplicate_releases_it(self, db_session, business):
        _create(db_session, business)

        with pytest.raises(invoice_service.DuplicateInvoice):
            _create(db_session, business)

        assert not db_session.in_transaction()

    def test_a_refused_plan_limit_releases_it(self, monkeypatch, db_session, business):
        def over(*_a, **_kw):
            raise invoice_service.PlanLimitExceeded("allowance used up")

        monkeypatch.setattr(invoice_service, "check_plan_limit", over)

        with pytest.raises(invoice_service.PlanLimitExceeded):
            _create(db_session, business)

        assert not db_session.in_transaction()

    def test_an_accepted_upload_releases_it_with_its_commit(self, db_session, business):
        invoice = _create(db_session, business)
        # ``refresh`` after the commit opens a read; the write that held the
        # lock is already committed, which is what releases it.
        assert invoice.id is not None
        assert invoice_service.find_duplicate(
            db_session, business.id, digest=invoice.file_hash
        ).id == invoice.id
