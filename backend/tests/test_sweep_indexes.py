"""The two sweeps that read every tenant at once must read them through an index.

Every other query in the product is tenant-scoped, and every index on these
tables leads with ``business_id`` to serve it. The periodic sweeps are the
exception: they ask "what does *anyone* have", constrain no ``business_id``, and
so cannot use any of those indexes — a leading column the query does not
constrain cannot be searched.

That failure is silent in the way that keeps it. The reaper commits only when it
found something, so on a healthy deployment a full scan of the invoices table
produces no rows, no log line and no error — just an hourly cost that grows with
the table. It went unnoticed long enough for the beat entry to describe it as
"one indexed query" while the index it named did not exist.

So these tests plan the SQL the production functions actually emit, rather than
asserting that an index is declared. A declaration is not a plan: the reaper was
already covered by ``ix_invoices_business_status`` on paper, and that index
cannot answer its query. Capturing the statement also means a predicate that
drifts away from the index — a column added to the ``WHERE``, a status test
rewritten — fails here rather than quietly reverting to a scan.

Both tests seed a table shaped like a real one and ``ANALYZE`` before planning,
because an index is only ever *offered* to the planner; which one it takes is a
cost decision, and with no statistics SQLite guesses from the query alone. On an
unanalysed table it picks ``ix_alerts_deleted_at`` for the digest — an index on
the column that is null for every live row, so the "search" it plans reads the
whole table anyway. That is the same wrong answer as before the fix and it looks
like a different one, which is precisely what these tests exist to tell apart.
The rows below are what make the choice mean something: a long history, almost
all of it closed, with the handful the sweep wants at the far end of it.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.business import Business
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services.alert_delivery import send_pending_alerts
from app.services.invoice_service import reap_stalled_parses
from tests.conftest import BUSINESS_GSTIN

# Enough rows for a scan and a search to cost visibly different amounts. The
# point is the ratio, not the size: the statuses the sweeps look for are a
# rounding error in a real table, which is exactly why an index pays.
HISTORY = 400


@pytest.fixture()
def tenant(db_session) -> Business:
    """A business for the swept rows to hang off — the FKs are enforced here."""
    business = Business(
        gstin=BUSINESS_GSTIN,
        legal_name="Umang Traders Private Limited",
        state_code=BUSINESS_GSTIN[:2],
    )
    db_session.add(business)
    db_session.commit()
    db_session.refresh(business)
    return business


def _analyze(session) -> None:
    """Give the planner the statistics it would have against a real table."""
    session.get_bind().raw_connection().cursor().execute("ANALYZE")


def _plan(session, statement: str, parameters) -> str:
    """SQLite's query plan for *statement*, as one string."""
    rows = (
        session.get_bind()
        .raw_connection()
        .cursor()
        .execute("EXPLAIN QUERY PLAN " + statement, parameters)
    )
    return " | ".join(str(row[-1]) for row in rows)


def _first_select(session, run) -> tuple[str, object]:
    """Run *run*, returning the first SELECT it emits against the swept table."""
    statements: list[tuple[str, object]] = []

    def _record(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", _record)
    try:
        run()
    finally:
        event.remove(bind, "before_cursor_execute", _record)

    assert statements, "the sweep issued no SELECT at all"
    return statements[0]


class TestTheStalledParseReaperIsIndexed:
    @pytest.fixture()
    def register(self, db_session, tenant) -> None:
        """A purchase register that has been read, with one parse stranded."""
        for _ in range(HISTORY):
            db_session.add(
                Invoice(
                    business_id=tenant.id,
                    invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED,
                )
            )
        db_session.add(
            Invoice(
                business_id=tenant.id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PROCESSING,
                updated_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db_session.commit()
        _analyze(db_session)

    def test_the_hourly_reaper_searches_an_index_rather_than_scanning_invoices(
        self, db_session, register
    ):
        statement, parameters = _first_select(
            db_session, lambda: reap_stalled_parses(db_session)
        )
        plan = _plan(db_session, statement, parameters)

        assert "ix_invoices_status_updated" in plan, plan
        # Not merely "an index was named": SQLite says SCAN when it walks one
        # end to end, which is the whole-table read this exists to stop.
        assert "SCAN" not in plan, plan

    def test_the_reaper_still_finds_the_row_the_plan_is_for(self, db_session, register):
        # A plan is worthless if the predicate stopped matching. A partial index
        # returns nothing at all for a query that drifts outside its ``WHERE``,
        # and that drift would leave the plan above looking healthier than ever
        # — so what the sweep actually did is asserted beside how it did it.
        assert reap_stalled_parses(db_session) == 1


class TestTheAlertDigestIsIndexed:
    @pytest.fixture(autouse=True)
    def _email_configured(self, monkeypatch):
        # The digest returns before it queries anything when email is off, and a
        # sweep that never ran plans nothing.
        monkeypatch.setattr(settings, "alerts_email_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

    @pytest.fixture()
    def history(self, db_session, tenant) -> None:
        """Years of alerts the business has dealt with, and one still to send."""
        for index in range(HISTORY):
            db_session.add(
                Alert(
                    business_id=tenant.id,
                    alert_type=AlertType.FILING_DEADLINE,
                    status=AlertStatus.DISMISSED if index % 2 else AlertStatus.READ,
                    title="GSTR-3B was due",
                    message="Filed.",
                )
            )
        db_session.add(
            Alert(
                business_id=tenant.id,
                alert_type=AlertType.FILING_DEADLINE,
                status=AlertStatus.PENDING,
                title="GSTR-3B is due",
                message="Due in three days.",
            )
        )
        db_session.commit()
        _analyze(db_session)

    @pytest.mark.skipif(
        sqlite3.sqlite_version_info < (3, 53),
        reason=(
            "SQLite before 3.53 plans this DISTINCT/ORDER BY by walking an index in "
            "business_id order, or the table, rather than searching the partial "
            "status index, whatever the query's shape (tried on 3.45: without the "
            "ORDER BY, and without the DISTINCT). The suite stands in for Postgres "
            "here, and only a planner that chooses as it does can say anything."
        ),
    )
    def test_the_digest_finds_its_tenants_through_an_index(self, db_session, history):
        statement, parameters = _first_select(
            db_session, lambda: send_pending_alerts(db_session)
        )
        plan = _plan(db_session, statement, parameters)

        assert "ix_alerts_status_business" in plan, plan
        assert "SCAN" not in plan, plan
        # What is asserted here is the search on ``status``, and only that. The
        # second column of that index exists so Postgres can answer the DISTINCT
        # without touching the rows; SQLite plans a temp b-tree for it whatever
        # the column order, and does not treat a partial index as covering even
        # when the query's predicate matches its own. That benefit is real —
        # measured — and invisible from here. See the note on the index in
        # models/alert.py rather than reading this test as covering it.
