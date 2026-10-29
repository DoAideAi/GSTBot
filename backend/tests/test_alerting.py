"""The daily filing-deadline sweep: what it says, when, and how often.

Every test here fixes ``today`` rather than letting the sweep read the clock.
That is not only determinism: the whole subject of this module is the distance
between a date and a deadline, so a suite that ran against the real date would
assert something different every morning and would pass or fail depending on
which side of the 11th it was run.

The dates below are chosen so one period, 2026-04, has both of its returns in
play at once: GSTR-1 was due on the 11th of May and GSTR-3B is due on the 20th.
A sweep on the 14th therefore has one overdue return and one approaching
deadline for the same tenant, which is the case the wording, the severity
ladder and the reopening rules all have to get right together.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.business import Business
from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.services import alerting
from app.services import filing as filing_service
from app.tasks import alert_tasks
from app.tasks.alert_tasks import sweep_filing_deadlines_task
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE

# The period every test is about, and the two dates it is due on.
PERIOD = "2026-04"
GSTR1_DUE = date(2026, 5, 11)
GSTR3B_DUE = date(2026, 5, 20)

# Three days after GSTR-1 was due and six before GSTR-3B is.
TODAY = date(2026, 5, 14)

# Signed up two days into the period under test, so 2026-04 is the first month
# this application holds invoices for and the only one it may speak about. Most
# tests want exactly that: two returns in play and nothing else in the way.
SIGNED_UP = datetime(2026, 4, 2, 10, 0)

# Older than every period the sweep looks back over — a business nothing is
# withheld from, used where the whole window is the subject.
LONG_ESTABLISHED = datetime(2025, 1, 1, 9, 0)


def make_business(db, *, gstin=BUSINESS_GSTIN, created=SIGNED_UP, **kwargs):
    """A tenant with an explicit signup date.

    ``created_at`` is a server default, so a row that is merely inserted gets
    "now" — which in this suite is the real clock and would put every business
    two years after the periods under test.
    """
    business = Business(
        gstin=gstin,
        legal_name="Umang Traders Private Limited",
        state_code=gstin[:2],
        created_at=created,
        updated_at=created,
        **kwargs,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def record_filing(db, business, return_type, *, period=PERIOD, filed_on=date(2026, 5, 9)):
    """Mark one return filed, the way the record-a-filing endpoint does."""
    row = GSTRReturn(
        business_id=business.id,
        period=period,
        return_type=return_type,
        status=ReturnStatus.FILED,
        filed_at=datetime(filed_on.year, filed_on.month, filed_on.day, 11, 0),
        arn="AA270426000000A",
    )
    db.add(row)
    db.commit()
    return row


def sweep(db, business, *, today=TODAY):
    """One tenant's sweep, committed — what the scheduled task does per row."""
    result = alerting.sweep_business(db, business, today=today)
    db.commit()
    return result


def alerts_for(db, business, *, return_type=None) -> list[Alert]:
    rows = [
        row
        for row in db.query(Alert)
        .filter_by(business_id=business.id, alert_type=AlertType.FILING_DEADLINE)
        .order_by(Alert.id)
        .all()
        if return_type is None
        or (row.context or {}).get("return_type") == return_type.value
    ]
    return rows


def one_alert(db, business, return_type) -> Alert:
    rows = alerts_for(db, business, return_type=return_type)
    assert len(rows) == 1, f"expected exactly one {return_type} alert, got {len(rows)}"
    return rows[0]


def standing(return_type, *, as_of, filed_on=None):
    """A standing built by hand, for the wording and severity helpers."""
    return filing_service.ReturnStanding(
        period=PERIOD,
        return_type=return_type,
        due_date=GSTR1_DUE if return_type is ReturnType.GSTR1 else GSTR3B_DUE,
        as_of=as_of,
        filed_on=filed_on,
    )


@pytest.fixture()
def business(db_session) -> Business:
    return make_business(db_session)


class _Retry(Exception):
    """Stands in for celery.exceptions.Retry, which is what .retry() raises."""


@pytest.fixture()
def retries(monkeypatch) -> list[BaseException | None]:
    """Make the task's retry decision observable without a broker.

    Celery binds ``self``, so the task is called as ``sweep_filing_deadlines_task()``
    and there is no fake to hand in; patching retry on the registered object
    keeps the code under test the object the worker actually runs.
    """
    recorded: list[BaseException | None] = []

    def fake_retry(exc=None, **kwargs):
        recorded.append(exc)
        return _Retry(str(exc))

    monkeypatch.setattr(sweep_filing_deadlines_task, "retry", fake_retry)
    return recorded


@pytest.fixture()
def sessions(monkeypatch, db_session) -> dict[str, int]:
    """Hand the task the test's session and count what it opens and closes.

    Closing for real would detach every object the test still holds, so the
    close is counted rather than performed. That count is the assertion: a
    connection leaked once per nightly run never comes back on its own, and
    the Postgres it leaks from is shared with three other products.
    """
    record = {"opened": 0, "closed": 0}

    class _Handle:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            record["closed"] += 1

    def factory():
        record["opened"] += 1
        return _Handle()

    monkeypatch.setattr(alert_tasks, "SessionLocal", factory)
    return record


# ---------------------------------------------------------------------------
# What gets raised, and when
# ---------------------------------------------------------------------------

class TestWhatTheSweepRaises:
    def test_an_approaching_and_a_missed_deadline_both_produce_an_alert(
        self, db_session, business
    ):
        result = sweep(db_session, business)

        assert result.raised == 2
        assert result.businesses == 1
        assert {row.period for row in alerts_for(db_session, business)} == {PERIOD}

    def test_a_missed_deadline_is_critical(self, db_session, business):
        sweep(db_session, business)

        alert = one_alert(db_session, business, ReturnType.GSTR1)
        assert alert.severity is AlertSeverity.CRITICAL
        assert alert.status is AlertStatus.PENDING
        assert alert.due_date == GSTR1_DUE

    def test_an_alert_carries_the_return_type_it_is_about(self, db_session, business):
        # The period is a column and the return type is not, so this is the
        # only thing that keeps the GSTR-1 and GSTR-3B alerts for one month
        # apart. Lose it and the next sweep matches the first row it finds and
        # rewrites one return's alert with the other's wording.
        sweep(db_session, business)

        stored = {
            (row.context or {}).get("return_type")
            for row in alerts_for(db_session, business)
        }
        assert stored == {ReturnType.GSTR1.value, ReturnType.GSTR3B.value}

    def test_nothing_is_sent_anywhere(self, db_session, business):
        # The row is raised and the product shows it. No channel exists yet,
        # and a null channel is how a future sender finds what it has not sent.
        sweep(db_session, business)

        for row in alerts_for(db_session, business):
            assert row.channel is None
            assert row.sent_at is None

    def test_a_deadline_further_out_than_the_lead_time_is_not_mentioned(
        self, db_session, business
    ):
        # 1 May: GSTR-1 is ten days off and GSTR-3B nineteen. Neither is news.
        result = sweep(db_session, business, today=date(2026, 5, 1))

        assert result.raised == 0
        assert alerts_for(db_session, business) == []

    def test_the_first_alert_lands_a_working_week_before_the_date(
        self, db_session, business
    ):
        first_day = GSTR1_DUE - timedelta(days=alerting.LEAD_DAYS)
        result = sweep(db_session, business, today=first_day)

        assert result.raised == 1
        assert one_alert(db_session, business, ReturnType.GSTR1).severity is (
            AlertSeverity.INFO
        )

    def test_nothing_is_raised_for_a_return_that_was_filed(self, db_session, business):
        record_filing(db_session, business, ReturnType.GSTR1)

        result = sweep(db_session, business)

        assert result.raised == 1
        assert alerts_for(db_session, business, return_type=ReturnType.GSTR1) == []


class TestWhatTheSweepWithholds:
    def test_a_period_that_closed_before_signup_is_not_mentioned(self, db_session):
        # Registered on 2 April, so April is the first month this application
        # holds invoices for. March's returns may well be unfiled; nothing here
        # knows, and six confident, wrong alerts on day one lose the channel.
        recent = make_business(db_session, created=SIGNED_UP)
        established = make_business(
            db_session, gstin=SUPPLIER_GSTIN_OTHER_STATE, created=LONG_ESTABLISHED
        )

        sweep(db_session, recent, today=TODAY)
        sweep(db_session, established, today=TODAY)

        # The same sweep, the same day, the same unfiled returns — and March is
        # only spoken about to the business that was here for it.
        assert {row.period for row in alerts_for(db_session, recent)} == {PERIOD}
        assert "2026-03" in {row.period for row in alerts_for(db_session, established)}

    def test_a_business_that_signed_up_today_is_told_nothing(self, db_session):
        business = make_business(db_session, created=datetime(2026, 5, 14, 10, 0))

        result = sweep(db_session, business, today=TODAY)

        assert result == alerting.SweepResult(businesses=1)
        assert alerts_for(db_session, business) == []

    def test_a_business_with_no_signup_date_is_told_everything(self):
        # Only reachable from a hand-built row that was never flushed. There is
        # no date to be cautious about, so nothing is withheld.
        business = Business(
            gstin=BUSINESS_GSTIN, legal_name="Umang Traders", state_code="27", id=1
        )

        assert alerting._first_period(business) is None

    def test_the_window_stops_at_six_completed_periods(self, db_session):
        business = make_business(db_session, created=LONG_ESTABLISHED)

        result = sweep(db_session, business)

        # 2025-11 through 2026-04 as of May, two returns each, and nothing
        # older — an unfiled return from 2025-10 is a standing liability whose
        # alert was raised months ago, not a reminder to raise now.
        assert result.raised == 2 * alerting.WINDOW_PERIODS
        assert {row.period for row in alerts_for(db_session, business)} == {
            "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", PERIOD
        }

    def test_the_month_in_progress_is_not_asked_for(self, db_session):
        # The portal does not open a return until its month is over, so an
        # alert about May in May would be asking for sales that have not
        # happened yet.
        business = make_business(db_session, created=LONG_ESTABLISHED)

        sweep(db_session, business)

        assert "2026-05" not in {row.period for row in alerts_for(db_session, business)}


# ---------------------------------------------------------------------------
# The severity ladder
# ---------------------------------------------------------------------------

class TestHowLoudTheAlertIs:
    @pytest.mark.parametrize(
        ("days_out", "severity"),
        [
            (7, AlertSeverity.INFO),
            (4, AlertSeverity.INFO),
            (3, AlertSeverity.WARNING),
            (0, AlertSeverity.WARNING),
            (-1, AlertSeverity.CRITICAL),
        ],
    )
    def test_the_ladder_only_climbs(self, days_out, severity):
        as_of = GSTR3B_DUE - timedelta(days=days_out)
        assert alerting._severity(standing(ReturnType.GSTR3B, as_of=as_of)) is severity

    def test_a_return_filed_late_is_not_critical(self):
        # ``overdue`` is about an unmet obligation, not a punctual one. A return
        # filed after its date has still been filed, and the sweep closes the
        # alert rather than escalating it.
        late = standing(
            ReturnType.GSTR1, as_of=TODAY, filed_on=date(2026, 5, 13)
        )
        assert late.filed_late
        assert not late.overdue


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

class TestWhatTheAlertSays:
    def test_an_overdue_return_says_how_long_it_has_been(self):
        title, message = alerting.wording(standing(ReturnType.GSTR1, as_of=TODAY))

        assert title == "GSTR-1 for 2026-04 is overdue"
        assert "2026-05-11" in message
        assert "3 days ago" in message

    def test_one_day_is_singular(self):
        title, _ = alerting.wording(
            standing(ReturnType.GSTR3B, as_of=GSTR3B_DUE - timedelta(days=1))
        )
        assert title == "GSTR-3B for 2026-04 is due in 1 day"

    def test_the_day_it_is_due_says_today_rather_than_in_zero_days(self):
        title, message = alerting.wording(
            standing(ReturnType.GSTR3B, as_of=GSTR3B_DUE)
        )

        assert title == "GSTR-3B for 2026-04 is due today"
        assert "in 0 days" not in message

    def test_no_penalty_figure_is_quoted(self):
        # The rates are set by notification and have moved. A number here would
        # eventually be read as advice, confidently and wrongly.
        _, message = alerting.wording(standing(ReturnType.GSTR1, as_of=TODAY))

        assert "late fee" in message
        assert "%" not in message
        assert "₹" not in message

    def test_every_alert_says_how_to_close_it(self):
        # The alert is raised off this application's records, which are only as
        # current as what the business told it. Without this line, someone who
        # filed on the portal has no way to read the alert other than as wrong.
        for return_type in (ReturnType.GSTR1, ReturnType.GSTR3B):
            _, message = alerting.wording(standing(return_type, as_of=TODAY))
            assert "record it here" in message


# ---------------------------------------------------------------------------
# Running again tomorrow
# ---------------------------------------------------------------------------

class TestTheSweepIsIdempotent:
    def test_a_second_sweep_the_same_day_raises_nothing_new(self, db_session, business):
        sweep(db_session, business)
        again = sweep(db_session, business)

        assert again.raised == 0
        assert again.reopened == 0
        assert len(alerts_for(db_session, business)) == 2

    def test_the_wording_is_rewritten_as_the_date_approaches(self, db_session, business):
        sweep(db_session, business, today=date(2026, 5, 13))
        before = one_alert(db_session, business, ReturnType.GSTR3B).title
        assert "in 7 days" in before

        sweep(db_session, business, today=date(2026, 5, 19))
        after = one_alert(db_session, business, ReturnType.GSTR3B)

        assert "in 1 day" in after.title
        assert after.severity is AlertSeverity.WARNING

    def test_an_alert_that_gets_worse_is_escalated_in_place(self, db_session, business):
        sweep(db_session, business, today=date(2026, 5, 13))
        first_id = one_alert(db_session, business, ReturnType.GSTR3B).id

        sweep(db_session, business, today=date(2026, 5, 21))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)

        assert alert.id == first_id, "escalation raised a second row"
        assert alert.severity is AlertSeverity.CRITICAL


class TestClosingAnAlert:
    def test_recording_the_filing_resolves_it(self, db_session, business):
        sweep(db_session, business)
        record_filing(db_session, business, ReturnType.GSTR1)

        result = sweep(db_session, business)

        assert result.resolved == 1
        assert one_alert(db_session, business, ReturnType.GSTR1).status is (
            AlertStatus.RESOLVED
        )

    def test_a_filing_recorded_after_the_date_still_resolves_it(
        self, db_session, business
    ):
        sweep(db_session, business)
        record_filing(db_session, business, ReturnType.GSTR1, filed_on=date(2026, 5, 13))

        sweep(db_session, business)

        assert one_alert(db_session, business, ReturnType.GSTR1).status is (
            AlertStatus.RESOLVED
        )

    def test_resolved_is_not_dismissed(self, db_session, business):
        # The only way to ask later whether these alerts do anything: one means
        # the business acted, the other means they made it go away.
        sweep(db_session, business)
        record_filing(db_session, business, ReturnType.GSTR1)
        sweep(db_session, business)

        assert AlertStatus.RESOLVED is not AlertStatus.DISMISSED
        assert one_alert(db_session, business, ReturnType.GSTR1).status.value == "resolved"

    def test_a_resolved_alert_is_left_alone_by_later_sweeps(self, db_session, business):
        sweep(db_session, business)
        record_filing(db_session, business, ReturnType.GSTR1)
        sweep(db_session, business)

        again = sweep(db_session, business)

        assert again.resolved == 0
        assert again.raised == 0

    def test_undoing_the_filing_record_brings_the_alert_back(self, db_session, business):
        sweep(db_session, business)
        filing = record_filing(db_session, business, ReturnType.GSTR1)
        sweep(db_session, business)

        # The record is removed the way the application removes anything.
        filing.deleted_at = datetime(2026, 5, 15, 9, 0)
        db_session.commit()
        result = sweep(db_session, business)

        alert = one_alert(db_session, business, ReturnType.GSTR1)
        assert result.reopened == 1
        assert alert.status is AlertStatus.PENDING


class TestRespectingADismissal:
    def test_a_dismissed_alert_is_not_raised_again_tomorrow(self, db_session, business):
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.DISMISSED
        db_session.commit()

        result = sweep(db_session, business, today=date(2026, 5, 14))

        assert result.raised == 0
        assert result.reopened == 0
        assert one_alert(db_session, business, ReturnType.GSTR3B).status is (
            AlertStatus.DISMISSED
        )

    def test_a_dismissal_is_not_carried_across_a_change_in_severity(
        self, db_session, business
    ):
        # Dismissed while it was still a week out; the deadline has since been
        # missed. That is new information, not the thing that was dismissed.
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.DISMISSED
        db_session.commit()

        result = sweep(db_session, business, today=date(2026, 5, 21))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)

        assert result.reopened == 1
        assert alert.status is AlertStatus.PENDING
        assert alert.severity is AlertSeverity.CRITICAL

    def test_a_dismissal_survives_a_sweep_that_changes_only_the_wording(
        self, db_session, business
    ):
        # 5 to 4 days out is a different sentence and the same severity. If the
        # rewrite alone reopened it, a dismissal would last exactly one night.
        sweep(db_session, business, today=date(2026, 5, 15))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.DISMISSED
        db_session.commit()

        sweep(db_session, business, today=date(2026, 5, 16))

        assert one_alert(db_session, business, ReturnType.GSTR3B).status is (
            AlertStatus.DISMISSED
        )

    def test_a_read_alert_that_gets_worse_becomes_pending_again(
        self, db_session, business
    ):
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.READ
        db_session.commit()

        result = sweep(db_session, business, today=date(2026, 5, 21))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)

        assert alert.status is AlertStatus.PENDING
        # Read is not dismissed: it was never closed, so bringing it back to
        # pending is a refresh rather than a reopening, and counting it as one
        # would overstate how often dismissals are overridden.
        assert result.reopened == 0

    def test_a_sent_alert_that_gets_worse_becomes_pending_again(
        self, db_session, business
    ):
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.SENT
        db_session.commit()

        sweep(db_session, business, today=date(2026, 5, 21))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)

        assert alert.status is AlertStatus.PENDING
        assert alert.severity is AlertSeverity.CRITICAL

    def test_a_sent_alert_at_the_same_severity_stays_sent(
        self, db_session, business
    ):
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.SENT
        db_session.commit()

        sweep(db_session, business, today=date(2026, 5, 14))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)

        assert alert.status is AlertStatus.SENT

    def test_a_failed_delivery_leaves_the_alert_live(self, db_session, business):
        # The deadline is every bit as unmet; it is the sending that broke.
        sweep(db_session, business, today=date(2026, 5, 13))
        alert = one_alert(db_session, business, ReturnType.GSTR3B)
        alert.status = AlertStatus.FAILED
        db_session.commit()

        result = sweep(db_session, business, today=date(2026, 5, 14))

        assert result.raised == 0
        assert one_alert(db_session, business, ReturnType.GSTR3B).status is (
            AlertStatus.FAILED
        )


class TestAlertsThisBuildDoesNotUnderstand:
    def test_an_alert_for_an_unknown_return_type_is_left_where_it_is(
        self, db_session, business
    ):
        db_session.add(
            Alert(
                business_id=business.id,
                alert_type=AlertType.FILING_DEADLINE,
                severity=AlertSeverity.INFO,
                status=AlertStatus.PENDING,
                title="CMP-08 for 2026-04 is due",
                message="From a build that filed something this one does not.",
                period=PERIOD,
                due_date=date(2026, 5, 18),
                context={"return_type": "cmp08"},
            )
        )
        db_session.commit()

        sweep(db_session, business)

        stranger = [
            row
            for row in alerts_for(db_session, business)
            if (row.context or {}).get("return_type") == "cmp08"
        ]
        assert len(stranger) == 1
        assert stranger[0].title.startswith("CMP-08")

    def test_a_deleted_alert_does_not_block_a_new_one(self, db_session, business):
        sweep(db_session, business)
        alert = one_alert(db_session, business, ReturnType.GSTR1)
        alert.deleted_at = datetime(2026, 5, 14, 12, 0)
        db_session.commit()

        result = sweep(db_session, business)

        assert result.raised == 1

    def test_asking_about_no_periods_at_all_queries_nothing(self, db_session, business):
        """``_existing`` answers an empty ask without going to the database.

        ``sweep_business`` returns early when its window comes out empty, so
        this is the second of two guards and nothing in the product reaches it
        — today. What makes it worth keeping rather than deleting is what the
        query does without it: ``Alert.period.in_([])`` is a degenerate ``IN``,
        which SQLAlchemy emits with a warning and which the two backends here
        do not compile the same way. An empty ask is not a database question,
        and the cheapest correct answer is the empty one.

        A caller with an alert on file proves the ``{}`` is the empty *ask*
        being honoured rather than the tenant simply having nothing.
        """
        from sqlalchemy import event

        sweep(db_session, business)
        assert alerts_for(db_session, business), "fixture should leave alerts on file"

        statements: list[str] = []
        engine = db_session.get_bind()

        def _record(conn, cursor, statement, parameters, context, executemany):
            if "from alerts" in " ".join(statement.split()).lower():
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            assert alerting._existing(db_session, business.id, []) == {}
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert statements == []


# ---------------------------------------------------------------------------
# Every tenant, one at a time
# ---------------------------------------------------------------------------

class TestTheSweepAcrossTenants:
    def test_each_business_gets_its_own_alerts(self, db_session):
        first = make_business(db_session)
        second = make_business(db_session, gstin=SUPPLIER_GSTIN_OTHER_STATE)
        record_filing(db_session, second, ReturnType.GSTR1)

        result = alerting.sweep_filing_deadlines(db_session, today=TODAY)

        assert result.businesses == 2
        assert len(alerts_for(db_session, first, return_type=ReturnType.GSTR1)) == 1
        assert alerts_for(db_session, second, return_type=ReturnType.GSTR1) == []

    def test_a_deactivated_business_is_skipped(self, db_session):
        business = make_business(db_session, is_active=False)

        result = alerting.sweep_filing_deadlines(db_session, today=TODAY)

        assert result.businesses == 0
        assert alerts_for(db_session, business) == []

    def test_a_deleted_business_is_skipped(self, db_session):
        business = make_business(db_session)
        business.deleted_at = datetime(2026, 5, 1, 9, 0)
        db_session.commit()

        result = alerting.sweep_filing_deadlines(db_session, today=TODAY)

        assert result.businesses == 0
        assert alerts_for(db_session, business) == []

    def test_one_tenants_failure_does_not_end_the_sweep(self, db_session, monkeypatch):
        # The failure this whole design is about: a nightly job that dies on the
        # third tenant and never reaches the four-hundredth.
        first = make_business(db_session)
        second = make_business(db_session, gstin=SUPPLIER_GSTIN_OTHER_STATE)
        real = alerting.sweep_business

        def explode(db, business, *, today):
            if business.id == first.id:
                raise RuntimeError("this tenant's data is unreadable")
            return real(db, business, today=today)

        monkeypatch.setattr(alerting, "sweep_business", explode)
        result = alerting.sweep_filing_deadlines(db_session, today=TODAY)

        assert result.failed == 1
        assert result.businesses == 2
        assert result.raised == 2, "the second tenant was still swept"
        assert alerts_for(db_session, first) == []
        assert len(alerts_for(db_session, second)) == 2

    def test_a_failing_tenant_leaves_nothing_half_written(self, db_session, monkeypatch):
        business = make_business(db_session)
        real = alerting.sweep_business

        def half_then_fail(db, business, *, today):
            real(db, business, today=today)
            raise RuntimeError("after the rows were added, before the commit")

        monkeypatch.setattr(alerting, "sweep_business", half_then_fail)
        alerting.sweep_filing_deadlines(db_session, today=TODAY)

        assert alerts_for(db_session, business) == []

    def test_the_sweep_reads_the_clock_when_it_is_not_given_a_date(
        self, db_session, monkeypatch
    ):
        # The scheduled task passes no date, so this is the path production
        # takes — and it has to be the Indian date, not the box's.
        seen: list[date] = []
        monkeypatch.setattr(alerting.gst_calendar, "today_ist", lambda: TODAY)
        monkeypatch.setattr(
            alerting,
            "sweep_business",
            lambda db, business, *, today: seen.append(today)
            or alerting.SweepResult(businesses=1),
        )
        make_business(db_session)

        alerting.sweep_filing_deadlines(db_session)

        assert seen == [TODAY]


class TestWhatTheSweepReports:
    def test_the_result_is_json_serialisable_for_the_task_backend(self):
        result = alerting.SweepResult(
            businesses=2, raised=3, reopened=1, resolved=1, failed=0
        )

        assert result.as_dict() == {
            "businesses": 2,
            "raised": 3,
            "reopened": 1,
            "resolved": 1,
            "failed": 0,
        }


# ---------------------------------------------------------------------------
# The schedule that runs it
# ---------------------------------------------------------------------------

class TestTheScheduledTask:
    def test_the_schedule_names_a_task_that_is_registered(self):
        # A beat entry naming a task that no worker has registered is not an
        # error anywhere: beat publishes it, the worker rejects it as unknown,
        # and the sweep silently never runs.
        from app.celery_app import celery_app

        # What the worker does on boot, and the only thing that puts the
        # ``include`` modules' tasks in the registry — constructing the app
        # merely records the module names. Without this the assertion below
        # passes on whether some *earlier test file* happened to import
        # app.tasks.invoice_tasks, which is why it read green in a full run and
        # red on its own: alert_tasks is imported by this file's own subject,
        # invoice_tasks by nothing here. Registering the schedule's tasks is a
        # property of the worker, so the worker's own import is what to ask.
        celery_app.loader.import_default_modules()

        scheduled = {
            entry["task"] for entry in celery_app.conf.beat_schedule.values()
        }
        assert scheduled, "the beat schedule is empty"
        for name in scheduled:
            assert name in celery_app.tasks, f"{name} is scheduled but not registered"

    def test_the_sweep_runs_in_the_timezone_the_deadlines_are_in(self):
        from app.celery_app import DEADLINE_SWEEP_HOUR, celery_app

        # Beat reads a crontab entry in ``timezone``. On UTC, 07:00 would be
        # half past noon in India — after the morning the alert exists to reach.
        assert celery_app.conf.timezone == "Asia/Kolkata"

        schedule = celery_app.conf.beat_schedule["filing-deadline-sweep"]["schedule"]
        assert schedule.hour == {DEADLINE_SWEEP_HOUR}
        assert schedule.minute == {0}

    def test_the_sweep_runs_once_a_day(self):
        # Every field below the hour pinned, every field above it open. A
        # crontab that left day_of_week or day_of_month narrowed would run
        # weekly or monthly and still look like a daily schedule here.
        from app.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule["filing-deadline-sweep"]["schedule"]
        assert len(schedule.hour) == 1
        assert len(schedule.day_of_week) == 7
        assert len(schedule.day_of_month) == 31
        assert len(schedule.month_of_year) == 12

    def test_the_task_reports_what_the_sweep_did(self, sessions, monkeypatch):
        monkeypatch.setattr(
            alert_tasks.alerting,
            "sweep_filing_deadlines",
            lambda db: alerting.SweepResult(businesses=1, raised=2),
        )

        result = sweep_filing_deadlines_task()

        # A dict, not a SweepResult: the result backend serialises this to JSON
        # and a dataclass would fail there rather than here.
        assert result == {
            "businesses": 1,
            "raised": 2,
            "reopened": 0,
            "resolved": 0,
            "failed": 0,
        }
        assert sessions["closed"] == 1

    def test_a_sweep_that_cannot_reach_the_database_is_retried(
        self, sessions, retries, monkeypatch
    ):
        # Reaching the handler at all means something under the per-tenant
        # rollback broke — the tenant query itself, or the connection. Worth
        # one more try in ten minutes; not worth hammering, because the sweep
        # runs again tomorrow from the same starting point.
        boom = RuntimeError("could not connect to the database")

        def explode(db):
            raise boom

        monkeypatch.setattr(alert_tasks.alerting, "sweep_filing_deadlines", explode)

        with pytest.raises(_Retry):
            sweep_filing_deadlines_task()

        assert retries == [boom]

    def test_the_session_is_closed_even_when_the_sweep_fails(
        self, sessions, retries, monkeypatch
    ):
        # A long-lived worker that leaks a connection per failed run exhausts
        # the shared Postgres pool, and takes the other products with it.
        def explode(db):
            raise RuntimeError("the database is down")

        monkeypatch.setattr(alert_tasks.alerting, "sweep_filing_deadlines", explode)

        with pytest.raises(_Retry):
            sweep_filing_deadlines_task()

        assert sessions["closed"] == 1


class TestTwoSweepsAtOnce:
    """P20 M5: a redelivered task, a second beat or a run by hand overlapping
    the morning sweep — both found no alert and both inserted one. The pair
    outlived the filing (only one is resolved), and the other was emailed every
    morning. The sweep now runs only if it holds the sweep lock."""

    def test_a_sweep_that_cannot_take_the_lock_changes_nothing(
        self, db_session, business, monkeypatch, caplog
    ):
        from contextlib import contextmanager

        from app.models.alert import Alert

        @contextmanager
        def held(_db):
            yield False

        monkeypatch.setattr(alerting, "_sole_sweep", held)
        result = alerting.sweep_filing_deadlines(db_session, today=date(2026, 5, 18))
        assert (result.businesses, result.raised) == (0, 0)
        assert db_session.query(Alert).count() == 0
        assert any("another sweep is running" in r.getMessage() for r in caplog.records)

    def test_the_sole_sweep_still_raises(self, db_session, business):
        from app.models.alert import Alert

        result = alerting.sweep_filing_deadlines(db_session, today=date(2026, 5, 18))
        assert result.raised >= 1
        assert db_session.query(Alert).count() == result.raised


class TestTheSweepPaysAFixedCostPerTenant:
    """P38 M8: every tenant was read twice, and nothing said what it cost.

    The sweep commits after each business, so one tenant's bad data costs only
    its own alerts, and a commit expires every object in the session. The next
    business in the loop had been loaded as an ORM row and was read again from
    the database on first touch: one SELECT on ``businesses`` per tenant, every
    day, on top of the one that had already loaded it. The docstring said "two
    queries each", and a sweep measured at eight per tenant went unnoticed for
    the same reason that reload did. The sweep reads only id and created_at,
    so it now loads those as plain rows, which a commit cannot expire, and this
    pins what a tenant costs.
    """

    @staticmethod
    def _sweep_statements(db, count, start=0):
        from sqlalchemy import event

        from app.services.gstin import compute_check_digit

        for i in range(start, start + count):
            body = f"27AAGCB{8000 + i:04d}J1Z"
            db.add(Business(gstin=body + compute_check_digit(body), legal_name=f"T{i}"))
        db.commit()
        statements: list[str] = []

        def record(conn, cursor, statement, *args):
            statements.append(" ".join(statement.split()).lower())

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            alerting.sweep_filing_deadlines(db, today=date(2026, 11, 15))
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return statements

    def test_businesses_are_read_once_however_many_there_are(self, db_session):
        statements = self._sweep_statements(db_session, 6)
        reads = [s for s in statements if s.startswith("select") and "from businesses" in s]
        assert len(reads) == 1, reads

    def test_each_tenant_costs_the_same_fixed_number_of_statements(self, db_session):
        two = len(self._sweep_statements(db_session, 2))
        # Only fresh tenants in the second sweep too: the first two now have
        # their alerts, which is less work, not the same work twice.
        for business in db_session.query(Business).all():
            business.is_active = False
        db_session.commit()
        six = len(self._sweep_statements(db_session, 6, start=2))
        per_tenant = (six - two) / 4
        assert per_tenant == int(per_tenant)
        # Two returns' standings, existing alerts and the alerts it raises, and
        # the s.16(4) pass's purchases. A ninth is new work per tenant per day.
        assert per_tenant <= 7, per_tenant
