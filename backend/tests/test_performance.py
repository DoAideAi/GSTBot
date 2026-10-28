"""M8 — performance optimizations: caching, index coverage, query reduction.

Each test asserts an observable property of the fix rather than benchmarking
wall-clock time, which is unstable in CI.
"""
from __future__ import annotations

from unittest.mock import patch

from app.services import gstin as gstin_service
from app.services.invoice_service import TenantSnapshot, effective_plan

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
        """The three consumers (build, validate, unreadable) should not each
        fetch independently.  We verify structurally: preview() passes its
        single _invoices() read to both build_gstr1 and validate_period.
        """
        from app.services import filing
        calls = []
        original_invoices = filing._invoices

        def tracking_invoices(*args, **kwargs):
            calls.append(1)
            return original_invoices(*args, **kwargs)

        with patch.object(filing, "_invoices", side_effect=tracking_invoices):
            filing.preview(db_session, business, "2026-01", filing.ReturnType.GSTR1)

        assert len(calls) == 1, (
            f"_invoices was called {len(calls)} times; "
            "preview() should read once and pass the list through"
        )
