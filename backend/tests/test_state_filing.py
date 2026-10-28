"""M3 state machine: filing return lifecycle — DRAFT → FILED, IMPORTED for 2B.

States: DRAFT, READY, FILED, IMPORTED.

Guards:
- record_filing refuses return types not in DUE_DAY (GSTR2B cannot be filed).
- record_filing refuses a filing date in the future.
- record_filing refuses a filing date before the period ends.

Side effects:
- record_filing sets status to FILED and populates filed_at and due_date.
- Omitting ARN on a re-record does not clear a stored ARN.

Idempotency:
- Re-recording the same period+type updates the existing row.
"""
from __future__ import annotations

from datetime import date

from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.services.filing import FilingNotRecordable, record_filing

# -----------------------------------------------------------------------
# ReturnStatus contract
# -----------------------------------------------------------------------

class TestReturnStatusContract:

    def test_all_four_statuses_can_be_stored(self, db_session, business):
        periods = iter(
            [f"2026-0{i}" for i in range(1, 10)]
            + [f"2026-{i}" for i in range(10, 13)]
        )
        for s in ReturnStatus:
            rec = GSTRReturn(
                business_id=business.id,
                period=next(periods),
                return_type=ReturnType.GSTR1,
                status=s,
            )
            db_session.add(rec)
            db_session.commit()
            db_session.refresh(rec)
            assert rec.status is s

    def test_all_three_return_types_can_be_stored(
        self, db_session, business,
    ):
        for rt in ReturnType:
            rec = GSTRReturn(
                business_id=business.id,
                period="2026-04",
                return_type=rt,
                status=ReturnStatus.DRAFT,
            )
            db_session.add(rec)
            db_session.commit()
            db_session.refresh(rec)
            assert rec.return_type is rt


# -----------------------------------------------------------------------
# record_filing sets FILED status
# -----------------------------------------------------------------------

class TestRecordFilingSetsStatus:

    def test_recording_a_gstr1_sets_status_to_filed(
        self, db_session, business,
    ):
        rec = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 15),
        )
        assert rec.status is ReturnStatus.FILED

    def test_recording_a_gstr3b_sets_status_to_filed(
        self, db_session, business,
    ):
        rec = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR3B,
            filed_on=date(2026, 4, 15),
        )
        assert rec.status is ReturnStatus.FILED

    def test_a_filed_return_has_filed_at_and_due_date(
        self, db_session, business,
    ):
        rec = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 15),
        )
        assert rec.filed_at is not None
        assert rec.due_date is not None


# -----------------------------------------------------------------------
# record_filing guards
# -----------------------------------------------------------------------

class TestRecordFilingGuards:

    def test_filing_a_gstr2b_is_refused(self, db_session, business):
        import pytest

        with pytest.raises(FilingNotRecordable, match="not a return"):
            record_filing(
                db_session, business, "2026-03",
                ReturnType.GSTR2B,
                filed_on=date(2026, 4, 15),
            )

    def test_a_future_filing_date_is_refused(
        self, db_session, business,
    ):
        import pytest

        with pytest.raises(
            FilingNotRecordable, match="in the future"
        ):
            record_filing(
                db_session, business, "2026-03",
                ReturnType.GSTR1,
                filed_on=date(2099, 1, 1),
            )

    def test_a_filing_date_before_period_ends_is_refused(
        self, db_session, business,
    ):
        import pytest

        with pytest.raises(
            FilingNotRecordable, match="had not ended"
        ):
            record_filing(
                db_session, business, "2026-03",
                ReturnType.GSTR1,
                filed_on=date(2026, 3, 15),
            )


# -----------------------------------------------------------------------
# Idempotency: re-recording updates the existing row
# -----------------------------------------------------------------------

class TestRecordFilingIdempotency:

    def test_re_recording_same_period_returns_same_row(
        self, db_session, business,
    ):
        first = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 15),
        )
        second = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 20),
        )
        assert first.id == second.id

    def test_omitting_arn_on_re_record_does_not_clear_stored_arn(
        self, db_session, business,
    ):
        record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 15),
            arn="AA270426000001X",
        )
        updated = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 20),
        )
        assert updated.arn == "AA270426000001X"

    def test_supplying_a_new_arn_replaces_the_old_one(
        self, db_session, business,
    ):
        record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 15),
            arn="AA270426000001X",
        )
        updated = record_filing(
            db_session, business, "2026-03", ReturnType.GSTR1,
            filed_on=date(2026, 4, 20),
            arn="AA270420000002Y",
        )
        assert updated.arn == "AA270420000002Y"


# -----------------------------------------------------------------------
# IMPORTED status for GSTR-2B
# -----------------------------------------------------------------------

class TestImportedStatus:

    def test_a_gstr2b_row_can_be_stored_as_imported(
        self, db_session, business,
    ):
        rec = GSTRReturn(
            business_id=business.id,
            period="2026-04",
            return_type=ReturnType.GSTR2B,
            status=ReturnStatus.IMPORTED,
        )
        db_session.add(rec)
        db_session.commit()
        db_session.refresh(rec)
        assert rec.status is ReturnStatus.IMPORTED
        assert rec.return_type is ReturnType.GSTR2B
