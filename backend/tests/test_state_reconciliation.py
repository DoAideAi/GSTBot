"""M3 state machine: reconciliation run lifecycle — RUNNING → COMPLETED|FAILED.

Guards:
- ConcurrentReconciliation prevents two RUNNING rows for the same period.
- NoGSTR2BImported prevents running without a 2B.

Side effects:
- A completed run populates counts, timestamps, and ITC figures.
- A failed run rolls back partial invoice status changes and records the error.
- _apply_statuses maps MatchCategory to InvoiceStatus for non-carried findings.

Idempotency:
- Multiple completed runs for the same period accumulate as a history.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models.reconciliation_run import (
    MatchCategory,
    ReconciliationRun,
    ReconciliationStatus,
)

ZERO = Decimal("0.00")


def _run(db, business, *, period="2026-04",
         status=ReconciliationStatus.RUNNING) -> ReconciliationRun:
    run = ReconciliationRun(
        business_id=business.id,
        period=period,
        status=status,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# -----------------------------------------------------------------------
# ReconciliationStatus contract
# -----------------------------------------------------------------------

class TestReconciliationStatusContract:

    def test_all_four_statuses_can_be_stored(self, db_session, business):
        for s in ReconciliationStatus:
            run = ReconciliationRun(
                business_id=business.id,
                period="2026-04",
                status=s,
            )
            db_session.add(run)
            db_session.commit()
            db_session.refresh(run)
            assert run.status is s


# -----------------------------------------------------------------------
# MatchCategory contract
# -----------------------------------------------------------------------

class TestMatchCategoryContract:

    def test_all_five_categories_exist(self):
        assert len(MatchCategory) == 5
        assert MatchCategory.MATCHED.value == "matched"
        assert MatchCategory.MISMATCHED.value == "mismatched"
        assert MatchCategory.MISSING_IN_2B.value == "missing_in_2b"
        assert MatchCategory.MISSING_IN_BOOKS.value == "missing_in_books"
        assert MatchCategory.DUPLICATE.value == "duplicate"


# -----------------------------------------------------------------------
# RUNNING → COMPLETED transition
# -----------------------------------------------------------------------

class TestRunningToCompleted:

    def test_a_running_run_can_be_completed(self, db_session, business):
        run = _run(db_session, business)
        assert run.status is ReconciliationStatus.RUNNING
        run.status = ReconciliationStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.matched_count = 5
        run.mismatched_count = 1
        run.total_invoices = 8
        run.itc_eligible = Decimal("45000.00")
        db_session.commit()
        db_session.refresh(run)
        assert run.status is ReconciliationStatus.COMPLETED
        assert run.matched_count == 5
        assert run.completed_at is not None

    def test_a_completed_run_has_started_at_and_completed_at(
        self, db_session, business,
    ):
        run = _run(db_session, business)
        assert run.started_at is not None
        run.status = ReconciliationStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        db_session.commit()
        db_session.refresh(run)
        assert run.started_at is not None
        assert run.completed_at is not None
        assert run.completed_at >= run.started_at


# -----------------------------------------------------------------------
# RUNNING → FAILED transition
# -----------------------------------------------------------------------

class TestRunningToFailed:

    def test_a_failed_run_records_the_error(self, db_session, business):
        run = _run(db_session, business)
        run.status = ReconciliationStatus.FAILED
        run.completed_at = datetime.now(UTC)
        run.error = "Division by zero in tolerance computation"
        db_session.commit()
        db_session.refresh(run)
        assert run.status is ReconciliationStatus.FAILED
        assert "Division by zero" in run.error

    def test_a_failed_run_leaves_counts_at_zero(
        self, db_session, business,
    ):
        run = _run(db_session, business)
        run.status = ReconciliationStatus.FAILED
        run.completed_at = datetime.now(UTC)
        run.error = "Unexpected error"
        db_session.commit()
        db_session.refresh(run)
        assert run.matched_count == 0
        assert run.mismatched_count == 0
        assert run.total_invoices == 0
        assert run.itc_eligible == ZERO


# -----------------------------------------------------------------------
# Concurrent guard: two RUNNING rows for same period
# -----------------------------------------------------------------------

class TestConcurrentGuard:

    def test_two_running_rows_for_same_period_can_exist_in_db(
        self, db_session, business,
    ):
        """The DB does not prevent it — the guard is in the service layer."""
        r1 = _run(db_session, business, period="2026-04")
        r2 = _run(db_session, business, period="2026-04")
        assert r1.id != r2.id
        assert r1.status is ReconciliationStatus.RUNNING
        assert r2.status is ReconciliationStatus.RUNNING

    def test_the_service_query_detects_a_running_row(
        self, db_session, business,
    ):
        from sqlalchemy import select

        _run(db_session, business, period="2026-04")
        already = db_session.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.business_id == business.id,
                ReconciliationRun.period == "2026-04",
                ReconciliationRun.status
                == ReconciliationStatus.RUNNING,
            ).limit(1)
        )
        assert already is not None

    def test_a_completed_row_does_not_block_a_new_run(
        self, db_session, business,
    ):
        from sqlalchemy import select

        run = _run(db_session, business, period="2026-04")
        run.status = ReconciliationStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        db_session.commit()

        already = db_session.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.business_id == business.id,
                ReconciliationRun.period == "2026-04",
                ReconciliationRun.status
                == ReconciliationStatus.RUNNING,
            ).limit(1)
        )
        assert already is None


# -----------------------------------------------------------------------
# History: multiple runs for the same period accumulate
# -----------------------------------------------------------------------

class TestRunHistory:

    def test_multiple_completed_runs_for_same_period_accumulate(
        self, db_session, business,
    ):
        from sqlalchemy import select

        for i in range(3):
            run = _run(db_session, business, period="2026-04")
            run.status = ReconciliationStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            run.matched_count = i + 1
            db_session.commit()

        all_runs = db_session.scalars(
            select(ReconciliationRun).where(
                ReconciliationRun.business_id == business.id,
                ReconciliationRun.period == "2026-04",
            )
        ).all()
        assert len(all_runs) == 3
        assert [r.matched_count for r in all_runs] == [1, 2, 3]


# -----------------------------------------------------------------------
# Cross-tenant isolation
# -----------------------------------------------------------------------

class TestReconciliationTenantIsolation:

    def test_a_run_belongs_to_its_business(self, db_session, business):
        run = _run(db_session, business)
        assert run.business_id == business.id

    def test_a_running_row_for_another_business_is_not_detected(
        self, db_session, business,
    ):
        from sqlalchemy import select

        _run(db_session, business, period="2026-04")
        other_business_id = business.id + 9999
        already = db_session.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.business_id
                == other_business_id,
                ReconciliationRun.period == "2026-04",
                ReconciliationRun.status
                == ReconciliationStatus.RUNNING,
            ).limit(1)
        )
        assert already is None
