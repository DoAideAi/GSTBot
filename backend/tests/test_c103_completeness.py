"""C103 Pass 14, M9: features that were wired halfway."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.sql.dml import Update

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.usage import UsageRecord
from app.services import invoice_service
from app.services import usage as usage_service

USAGE = "/api/v1/subscriptions/usage"


def _uploaded(db_session, business, n: int) -> None:
    for i in range(n):
        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PARSED,
                invoice_number=f"U-{i}",
                invoice_date=date(2026, 4, 1),
                period="2026-04",
                total_value=Decimal("100"),
            )
        )
    db_session.commit()


class TestTheUsagePageReportsWhatIsCounted:
    """Nothing wrote a usage row, so the page — linked from the nav — said
    "No API calls recorded this month" to a business uploading all month."""

    def test_it_shows_the_invoices_uploaded_this_month_against_the_plan(
        self, auth_client, db_session, business, monkeypatch
    ):
        monkeypatch.setattr(invoice_service, "plan_limit", lambda business: 50)
        _uploaded(db_session, business, 3)

        usage = auth_client.get(USAGE).json()["usage"]
        assert usage[0] == {
            "endpoint": "invoice_uploads",
            "call_count": 3,
            "limit": 50,
            "period": invoice_service.month_of(),
        }

    def test_it_agrees_with_the_dashboard(self, auth_client, db_session, business):
        _uploaded(db_session, business, 2)
        usage = auth_client.get(USAGE).json()["usage"][0]
        plan = auth_client.get("/api/v1/dashboard").json()["plan_usage"]
        assert usage["call_count"] == plan["invoices_this_month"]
        assert usage["limit"] == plan["monthly_limit"]

    def test_a_bulk_validation_is_recorded(self, auth_client, paid_business):
        auth_client.post("/api/v1/meta/gstin/bulk", json={"gstins": ["27AAPFU0939F1ZV"]})
        auth_client.post("/api/v1/meta/gstin/bulk", json={"gstins": ["27AAPFU0939F1ZV"]})
        rows = {r["endpoint"]: r for r in auth_client.get(USAGE).json()["usage"]}
        assert rows["bulk_operation"]["call_count"] == 2


class TestRecordUsage:
    def test_it_increments_in_the_database(self, db_session, business):
        usage_service.record_usage(db_session, business.id, "bulk_operation")
        stale = db_session.query(UsageRecord).one()
        usage_service.record_usage(db_session, business.id, "bulk_operation", count=4)
        db_session.commit()
        db_session.refresh(stale)
        assert stale.call_count == 5

    def test_losing_the_race_to_insert_the_months_first_row_still_counts(
        self, db_session, business, monkeypatch
    ):
        """Two first requests of the month both find no row; the second insert
        hits the unique key. It used to be a read-then-insert, so that was an
        IntegrityError out of the request."""
        usage_service.record_usage(db_session, business.id, "bulk_operation")
        db_session.commit()

        real_execute = db_session.execute
        calls = {"n": 0}

        class _NoRows:
            rowcount = 0

        def first_update_finds_nothing(statement, *args, **kwargs):
            if isinstance(statement, Update):
                calls["n"] += 1
                if calls["n"] == 1:
                    return _NoRows()  # as if the row were not there yet
            return real_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "execute", first_update_finds_nothing)
        row = usage_service.record_usage(db_session, business.id, "bulk_operation")
        db_session.commit()
        assert calls["n"] == 2  # the bump, then the bump after losing the insert
        assert row.call_count == 2

    def test_the_month_is_the_indian_one(self, monkeypatch):
        """At 00:30 IST on 1 November it is still October in UTC."""
        from datetime import UTC, datetime

        from app.services import gst_calendar

        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 11, 1))
        assert usage_service.current_period() == "2026-11"
        assert datetime(2026, 10, 31, 19, 0, tzinfo=UTC).strftime("%Y-%m") == "2026-10"
