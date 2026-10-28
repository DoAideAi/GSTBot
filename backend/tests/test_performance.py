"""M8 — performance optimizations: caching, index coverage, query reduction.

Each test asserts an observable property of the fix rather than benchmarking
wall-clock time, which is unstable in CI.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import event

from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import Invoice, InvoiceSource, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.services import gstin as gstin_service
from app.services.invoice_service import TenantSnapshot, effective_plan
from tests.conftest import make_paid

# -----------------------------------------------------------------------
# GSTIN validation caching
# -----------------------------------------------------------------------

class TestGstinCacheAvoidsDuplicateWork:
    """is_valid and state_code_of are called per-invoice during filing and
    reconciliation.  Caching eliminates redundant check-digit computation
    when the same GSTIN appears on many invoices (the common case: a
    business buys repeatedly from the same suppliers).
    """

    def setup_method(self):
        gstin_service.is_valid.cache_clear()
        gstin_service.state_code_of.cache_clear()

    def test_is_valid_is_cached(self):
        gstin = "27AAPFU0939F1ZV"
        assert gstin_service.is_valid(gstin) is True
        assert gstin_service.is_valid(gstin) is True
        info = gstin_service.is_valid.cache_info()
        assert info.hits >= 1, "second call should hit the cache"
        assert info.misses == 1

    def test_is_valid_caches_invalid_gstins_too(self):
        assert gstin_service.is_valid("INVALID") is False
        assert gstin_service.is_valid("INVALID") is False
        info = gstin_service.is_valid.cache_info()
        assert info.hits >= 1

    def test_state_code_of_is_cached(self):
        gstin = "27AAPFU0939F1ZV"
        assert gstin_service.state_code_of(gstin) == "27"
        assert gstin_service.state_code_of(gstin) == "27"
        info = gstin_service.state_code_of.cache_info()
        assert info.hits >= 1

    def test_state_code_of_caches_invalid(self):
        assert gstin_service.state_code_of("NOPE") is None
        assert gstin_service.state_code_of("NOPE") is None
        info = gstin_service.state_code_of.cache_info()
        assert info.hits >= 1

    def test_cache_distinguishes_different_gstins(self):
        g1 = "27AAPFU0939F1ZV"
        g2 = "29AAGCR4375J1ZU"
        gstin_service.is_valid(g1)
        gstin_service.is_valid(g2)
        info = gstin_service.is_valid.cache_info()
        assert info.misses == 2

    def test_cache_has_bounded_size(self):
        assert gstin_service.is_valid.cache_info().maxsize == 2048
        assert gstin_service.state_code_of.cache_info().maxsize == 2048


# -----------------------------------------------------------------------
# TenantSnapshot avoids the double effective_plan query
# -----------------------------------------------------------------------

class TestTenantSnapshotQueriesEffectivePlanOnce:
    """TenantSnapshot.of() used to call effective_plan() then plan_limit()
    which called effective_plan() again — two Subscription table lookups
    for the same answer.
    """

    def test_effective_plan_called_once(self, db_session, business):
        call_count = 0
        original = (
            effective_plan.__wrapped__
            if hasattr(effective_plan, '__wrapped__')
            else effective_plan
        )

        def counting_effective_plan(biz):
            nonlocal call_count
            call_count += 1
            return original(biz)

        with patch(
            "app.services.invoice_service.effective_plan",
            side_effect=counting_effective_plan,
        ):
            TenantSnapshot.of(business)

        assert call_count == 1, (
            f"effective_plan was called {call_count} times; "
            "TenantSnapshot.of() should call it exactly once"
        )

    def test_snapshot_plan_and_limit_are_consistent(self, db_session, business):
        snap = TenantSnapshot.of(business)
        from app.core.config import settings
        expected_limit = settings.plan_limits.get(snap.plan, 0)
        assert snap.monthly_limit == expected_limit


# -----------------------------------------------------------------------
# Reconciliation run index coverage
# -----------------------------------------------------------------------

class TestReconciliationRunIndexCoversLatestCompletedQuery:
    """The partial index ix_reconciliation_runs_business_period_completed
    exists on the model and covers the latest_completed_run() query pattern.
    """

    def test_partial_index_is_declared(self):
        from app.models.reconciliation_run import ReconciliationRun
        indexes = {idx.name for idx in ReconciliationRun.__table__.indexes}
        assert "ix_reconciliation_runs_business_period_completed" in indexes

    def test_partial_index_columns(self):
        from app.models.reconciliation_run import ReconciliationRun
        idx = next(
            idx for idx in ReconciliationRun.__table__.indexes
            if idx.name == "ix_reconciliation_runs_business_period_completed"
        )
        col_names = [col.name for col in idx.columns]
        assert col_names == ["business_id", "period", "created_at"]


# -----------------------------------------------------------------------
# Filing service: validate_period + _unreadable_invoices query count
# -----------------------------------------------------------------------

class TestFilingPreviewReadsInvoicesOnce:
    """filing.preview() shares the invoice list between the builder and
    the validator, so the period's sales are loaded once, not twice.
    """

    def test_preview_passes_invoices_through(self, db_session, business):
        """The consumers (build, validate) should not each fetch
        independently.  We verify structurally: preview() passes its
        single _invoices() read to both build_gstr1 and validate_period.
        """
        from app.services import filing
        calls = {"_invoices": 0, "_unreadable_invoices": 0}
        orig_inv = filing._invoices
        orig_unread = filing._unreadable_invoices

        def track_invoices(*args, **kwargs):
            calls["_invoices"] += 1
            return orig_inv(*args, **kwargs)

        def track_unreadable(*args, **kwargs):
            calls["_unreadable_invoices"] += 1
            return orig_unread(*args, **kwargs)

        with (
            patch.object(filing, "_invoices", side_effect=track_invoices),
            patch.object(
                filing, "_unreadable_invoices", side_effect=track_unreadable,
            ),
        ):
            filing.preview(
                db_session, business, "2026-01", filing.ReturnType.GSTR1,
            )

        assert calls["_invoices"] == 1, (
            f"_invoices called {calls['_invoices']} times; should be 1"
        )
        assert calls["_unreadable_invoices"] == 1, (
            f"_unreadable_invoices called "
            f"{calls['_unreadable_invoices']} times; should be 1"
        )


# -----------------------------------------------------------------------
# Bulk invoice reads leave the extracted document behind
# -----------------------------------------------------------------------

_DOCUMENT_COLUMNS = ("raw_text", "extraction", "line_items")


def _selects_column(statement: str, column: str, table: str = "invoices") -> bool:
    # Bounded, because ``extraction`` is a prefix of ``extraction_confidence``,
    # which every read does and should select.
    return re.search(rf"\b{table}\.{column}\b", statement) is not None


def _invoice_selects(session, run, table: str = "invoices") -> list[str]:
    """Every SELECT against *table* that *run* issues, lower-cased."""
    seen: list[str] = []

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalised = " ".join(statement.split()).lower()
        if normalised.startswith("select") and f"from {table}" in normalised:
            seen.append(normalised)

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _record)
    try:
        run()
    finally:
        event.remove(bind, "before_cursor_execute", _record)
    return seen


def _bulk_selects(selects: list[str]) -> list[str]:
    # The register read is the one selecting the row's figures; a COUNT or a
    # SUM issued alongside it never carries the document either way.
    return [s for s in selects if "invoices.taxable_value" in s and "count(" not in s]


def _seed_scanned_purchases(db_session, business, *, period="2026-04", count=3):
    """Parsed purchases carrying the kind of document an OCR'd PDF leaves."""
    for index in range(count):
        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.PURCHASE,
                period=period,
                status=InvoiceStatus.PARSED,
                source=InvoiceSource.UPLOAD,
                counterparty_gstin="29AAGCR4375J1ZU",
                counterparty_name=f"Supplier {index}",
                invoice_number=f"P-{index:04d}",
                invoice_date=date(2026, 4, 1 + index),
                taxable_value=Decimal("1000.00"),
                igst=Decimal("180.00"),
                total_value=Decimal("1180.00"),
                tax_rate=Decimal("18.00"),
                itc_eligible=True,
                raw_text="OCR " * 20_000,
                extraction={"warnings": ["low contrast scan"], "blob": "x" * 5_000},
                line_items=[{"description": "Widget", "hsn": "8471", "amount": "1000.00"}],
            )
        )
    db_session.commit()
    db_session.expire_all()


class TestBulkInvoiceReadsDeferTheDocument:
    """raw_text and extraction are the whole uploaded document and the model's
    answer about it; no screen that lists or totals invoices reads them.
    """

    def test_the_register_page_does_not_select_the_document(
        self, db_session, auth_client, business
    ):
        _seed_scanned_purchases(db_session, business)
        responses = []
        selects = _invoice_selects(
            db_session, lambda: responses.append(auth_client.get("/api/v1/invoices"))
        )
        assert responses[0].status_code == 200
        assert len(responses[0].json()["items"]) == 3
        reads = _bulk_selects(selects)
        assert reads, "the register read was not observed"
        for column in _DOCUMENT_COLUMNS:
            assert not any(_selects_column(s, column) for s in reads), column

    def test_the_register_page_still_serves_every_figure(
        self, db_session, auth_client, business
    ):
        _seed_scanned_purchases(db_session, business, count=1)
        item = auth_client.get("/api/v1/invoices").json()["items"][0]
        assert item["invoice_number"] == "P-0000"
        assert Decimal(item["invoice_value"]) == Decimal("1180.00")

    def test_the_detail_screen_still_gets_the_document(
        self, db_session, auth_client, business
    ):
        _seed_scanned_purchases(db_session, business, count=1)
        invoice_id = auth_client.get("/api/v1/invoices").json()["items"][0]["id"]
        detail = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()
        assert detail["warnings"] == ["low contrast scan"]
        assert detail["line_items"][0]["hsn"] == "8471"

    def test_the_itc_register_does_not_select_the_document(self, db_session, business):
        from app.services import itc
        _seed_scanned_purchases(db_session, business)
        rows = []
        selects = _invoice_selects(
            db_session,
            lambda: rows.extend(itc.purchase_invoices(db_session, business.id, "2026-04")),
        )
        assert len(rows) == 3
        for column in _DOCUMENT_COLUMNS:
            assert not any(_selects_column(s, column) for s in selects), column

    def test_the_reconciliation_books_do_not_select_the_document(
        self, db_session, business
    ):
        from app.services import reconciliation
        _seed_scanned_purchases(db_session, business)
        rows = []
        selects = _invoice_selects(
            db_session,
            lambda: rows.extend(
                reconciliation._book_invoices(db_session, business.id, "2026-04")
            ),
        )
        assert len(rows) == 3
        for column in _DOCUMENT_COLUMNS:
            assert not any(_selects_column(s, column) for s in selects), column

    def test_invoices_carried_from_another_period_do_not_select_the_document(
        self, db_session, business
    ):
        from app.services import reconciliation
        from app.services.gstr2b import GSTR2BRecord
        _seed_scanned_purchases(db_session, business, period="2026-03", count=1)
        record = GSTR2BRecord(
            supplier_gstin="29AAGCR4375J1ZU",
            invoice_number="P-0000",
            period="2026-03",
        )
        rows = []
        selects = _invoice_selects(
            db_session,
            lambda: rows.extend(
                reconciliation._carried_invoices(
                    db_session, business.id, [record], "2026-04"
                )
            ),
        )
        assert [row.invoice_number for row in rows] == ["P-0000"]
        for column in _DOCUMENT_COLUMNS:
            assert not any(_selects_column(s, column) for s in selects), column

    def test_filing_keeps_line_items_for_the_hsn_summary_but_not_the_text(
        self, db_session, business
    ):
        from app.services import filing
        _seed_scanned_purchases(db_session, business)
        rows = []
        selects = _invoice_selects(
            db_session,
            lambda: rows.extend(
                filing._invoices(db_session, business.id, "2026-04", InvoiceType.PURCHASE)
            ),
        )
        assert len(rows) == 3
        assert selects and all(_selects_column(s, "line_items") for s in selects)
        assert not any(_selects_column(s, "raw_text") for s in selects)
        assert not any(_selects_column(s, "extraction") for s in selects)

    def test_unreadable_rows_named_by_validation_do_not_select_the_document(
        self, db_session, business
    ):
        from app.services import filing
        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.SALES,
                period="2026-04",
                status=InvoiceStatus.FAILED,
                source=InvoiceSource.UPLOAD,
                invoice_number="BAD-1",
                raw_text="unreadable " * 5_000,
            )
        )
        db_session.commit()
        db_session.expire_all()
        rows = []
        selects = _invoice_selects(
            db_session,
            lambda: rows.extend(
                filing._unreadable_invoices(
                    db_session, business.id, "2026-04", InvoiceType.SALES
                )
            ),
        )
        assert [row.invoice_number for row in rows] == ["BAD-1"]
        for column in _DOCUMENT_COLUMNS:
            assert not any(_selects_column(s, column) for s in selects), column

    def test_a_deferred_column_still_loads_when_a_caller_reaches_for_it(
        self, db_session, business
    ):
        # Deferred, not dropped: the rare caller that needs the text pays one
        # lazy load for it rather than meeting an AttributeError.
        from app.services import itc
        _seed_scanned_purchases(db_session, business, count=1)
        (row,) = itc.purchase_invoices(db_session, business.id, "2026-04")
        assert row.raw_text.startswith("OCR ")
        assert row.extraction["warnings"] == ["low contrast scan"]


# -----------------------------------------------------------------------
# Summary reads of runs and returns leave their JSON payloads behind
# -----------------------------------------------------------------------

def _seed_heavy_run(db_session, business_id, period="2026-04"):
    db_session.add(
        ReconciliationRun(
            business_id=business_id,
            period=period,
            status=ReconciliationStatus.COMPLETED,
            matched_count=4000,
            report={"findings": [{"invoice_id": i, "category": "matched"} for i in range(4000)]},
        )
    )
    db_session.commit()
    db_session.expire_all()


def _seed_return(db_session, business_id, return_type, status, period="2026-04", **extra):
    db_session.add(
        GSTRReturn(
            business_id=business_id,
            period=period,
            return_type=return_type,
            status=status,
            invoice_count=4000,
            data={"b2b": [{"inum": f"INV-{i}"} for i in range(4000)]},
            validation_errors=[{"code": "x"}],
            **extra,
        )
    )
    db_session.commit()
    db_session.expire_all()


class TestSummaryReadsLeaveThePayloadBehind:
    """A run's ``report`` and a return's ``data`` hold one entry per invoice in
    the period. Screens that list runs or ask whether a period was filed read
    the counts beside them and nothing inside.
    """

    def test_the_runs_list_does_not_select_the_report(
        self, db_session, auth_client, business
    ):
        make_paid(db_session, business.id)
        _seed_heavy_run(db_session, business.id)
        responses = []
        selects = _invoice_selects(
            db_session,
            lambda: responses.append(auth_client.get("/api/v1/reconciliation")),
            table="reconciliation_runs",
        )
        assert responses[0].status_code == 200
        assert responses[0].json()["items"][0]["matched_count"] == 4000
        reads = [s for s in selects if "count(" not in s]
        assert reads, "the runs read was not observed"
        assert not any(
            _selects_column(s, "report", "reconciliation_runs") for s in reads
        )

    def test_a_single_run_still_carries_its_findings(self, db_session, business):
        # The ITC screen reads the capital share out of the report, so the
        # single-run lookup it shares with the dashboard must keep it.
        from app.services import reconciliation
        _seed_heavy_run(db_session, business.id)
        run = reconciliation.latest_completed_run(db_session, business.id, "2026-04")
        assert len(run.report["findings"]) == 4000

    def test_the_imported_2b_summary_does_not_select_the_statement(
        self, db_session, auth_client, business
    ):
        make_paid(db_session, business.id)
        _seed_return(db_session, business.id, ReturnType.GSTR2B, ReturnStatus.IMPORTED)
        responses = []
        selects = _invoice_selects(
            db_session,
            lambda: responses.append(auth_client.get("/api/v1/reconciliation/gstr2b/2026-04")),
            table="gstr_returns",
        )
        assert responses[0].status_code == 200
        assert responses[0].json()["invoice_count"] == 4000
        assert selects
        assert not any(_selects_column(s, "data", "gstr_returns") for s in selects)

    def test_asking_what_was_filed_does_not_select_the_returns(self, db_session, business):
        from app.services import filing
        _seed_return(
            db_session, business.id, ReturnType.GSTR1, ReturnStatus.FILED,
            arn="AA2704261234567",
        )
        found = {}
        selects = _invoice_selects(
            db_session,
            lambda: found.update(filing.filed_returns(db_session, business.id)),
            table="gstr_returns",
        )
        assert found[("2026-04", ReturnType.GSTR1)].arn == "AA2704261234567"
        assert selects
        for column in ("data", "validation_errors"):
            assert not any(_selects_column(s, column, "gstr_returns") for s in selects)

    def test_a_filed_return_still_loads_its_payload_on_access(self, db_session, business):
        from app.services import filing
        _seed_return(db_session, business.id, ReturnType.GSTR1, ReturnStatus.FILED)
        row = filing.filed_returns(db_session, business.id)[("2026-04", ReturnType.GSTR1)]
        assert len(row.data["b2b"]) == 4000
