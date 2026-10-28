"""The alert list, and the two things a business can do to an alert.

The sweep in ``test_alerting.py`` decides what gets raised; this is about what a
business can then see and close. The two files meet in one place on purpose —
``TestDismissingIsWhatTheSweepRespects`` dismisses through the API and then runs
the sweep — because that loop is the actual feature. A dismissal the sweep
ignored would still pass every test in this file individually.

Alerts here are inserted rather than swept up, so that severities, due dates and
statuses can be arranged deliberately. Two of them are not filing deadlines at
all: the listing is the one part of this that is not about deadlines
specifically, and a type filter tested only against rows of a single type proves
nothing.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.business import Business
from app.models.gstr_return import ReturnType
from app.services import alerting
from tests.conftest import SUPPLIER_GSTIN_SAME_STATE

PERIOD = "2026-04"
GSTR3B_DUE = date(2026, 5, 20)


def make_alert(
    db,
    business,
    *,
    alert_type: AlertType = AlertType.FILING_DEADLINE,
    severity: AlertSeverity = AlertSeverity.WARNING,
    status: AlertStatus = AlertStatus.PENDING,
    title: str = "GSTR-3B for 2026-04 is due in 6 days",
    period: str | None = PERIOD,
    due_date: date | None = GSTR3B_DUE,
    context: dict | None = None,
    deleted_at: date | None = None,
) -> Alert:
    alert = Alert(
        business_id=business.id,
        alert_type=alert_type,
        severity=severity,
        status=status,
        title=title,
        message=f"{title}. Recorded nowhere yet.",
        period=period,
        due_date=due_date,
        context=context if context is not None else {"return_type": "gstr3b"},
        deleted_at=deleted_at,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def listing(client, **params) -> dict:
    response = client.get("/api/v1/alerts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(payload: dict) -> list[str]:
    return [item["title"] for item in payload["items"]]


class TestWhatTheListingShows:
    def test_an_open_alert_is_listed(self, auth_client, db_session, business):
        make_alert(db_session, business)

        assert titles(listing(auth_client)) == ["GSTR-3B for 2026-04 is due in 6 days"]

    def test_a_dismissed_alert_is_not_in_the_way_by_default(
        self, auth_client, db_session, business
    ):
        make_alert(db_session, business, status=AlertStatus.DISMISSED)

        assert listing(auth_client)["items"] == []

    def test_a_resolved_alert_is_not_either(self, auth_client, db_session, business):
        make_alert(db_session, business, status=AlertStatus.RESOLVED)

        assert listing(auth_client)["items"] == []

    def test_an_alert_that_was_only_read_is_still_there(
        self, auth_client, db_session, business
    ):
        # Read is not handled. The deadline is every bit as unmet as it was
        # before somebody looked at it.
        make_alert(db_session, business, status=AlertStatus.READ)

        assert len(listing(auth_client)["items"]) == 1

    def test_an_alert_whose_delivery_failed_is_still_outstanding(
        self, auth_client, db_session, business
    ):
        # Nothing sends yet, so this status is unreachable today — but it is
        # the one a future sender writes, and an alert that disappears because
        # the sending broke is the worst possible reading of "open".
        make_alert(db_session, business, status=AlertStatus.FAILED)

        assert len(listing(auth_client)["items"]) == 1

    def test_the_closed_ones_can_be_asked_for(self, auth_client, db_session, business):
        make_alert(db_session, business, title="open one")
        make_alert(db_session, business, status=AlertStatus.DISMISSED, title="closed one")

        assert titles(listing(auth_client, scope="closed")) == ["closed one"]
        assert sorted(titles(listing(auth_client, scope="all"))) == ["closed one", "open one"]

    def test_a_soft_deleted_alert_is_gone_from_every_scope(
        self, auth_client, db_session, business
    ):
        make_alert(db_session, business, deleted_at=date(2026, 5, 1))

        assert listing(auth_client, scope="all")["items"] == []

    def test_an_unknown_scope_is_refused_rather_than_ignored(self, auth_client):
        # Silently falling back to "open" would show a caller asking for
        # closed alerts an empty list and let them conclude there are none.
        assert auth_client.get("/api/v1/alerts", params={"scope": "everything"}).status_code == 422


class TestTheOrderTheyArriveIn:
    def test_the_loudest_comes_first(self, auth_client, db_session, business):
        # Raised in the wrong order deliberately: the enum's own values sort
        # critical, info, warning alphabetically, so a listing that leaned on
        # the column would put "info" second.
        make_alert(db_session, business, severity=AlertSeverity.INFO, title="info")
        make_alert(db_session, business, severity=AlertSeverity.CRITICAL, title="critical")
        make_alert(db_session, business, severity=AlertSeverity.WARNING, title="warning")

        assert titles(listing(auth_client)) == ["critical", "warning", "info"]

    def test_the_soonest_deadline_leads_within_a_severity(
        self, auth_client, db_session, business
    ):
        make_alert(db_session, business, due_date=date(2026, 5, 20), title="later")
        make_alert(db_session, business, due_date=date(2026, 5, 11), title="sooner")

        assert titles(listing(auth_client)) == ["sooner", "later"]

    def test_an_alert_with_no_date_sorts_last(self, auth_client, db_session, business):
        # A supplier-risk alert has nothing to be due. It should not lead the
        # list simply because a null sorted first, which is what Postgres does
        # by default on an ascending order and SQLite does not.
        make_alert(db_session, business, due_date=None, period=None, title="undated")
        make_alert(db_session, business, due_date=date(2026, 6, 20), title="dated")

        assert titles(listing(auth_client)) == ["dated", "undated"]

    def test_severity_outranks_the_date(self, auth_client, db_session, business):
        # An overdue return outranks next week's reminder even though the
        # reminder's date is the one further away.
        make_alert(
            db_session,
            business,
            severity=AlertSeverity.INFO,
            due_date=date(2026, 5, 30),
            title="due soon",
        )
        make_alert(
            db_session,
            business,
            severity=AlertSeverity.CRITICAL,
            due_date=date(2026, 4, 11),
            title="overdue",
        )

        assert titles(listing(auth_client)) == ["overdue", "due soon"]


class TestNarrowingTheList:
    @pytest.fixture()
    def mixed(self, db_session, business):
        make_alert(db_session, business, title="deadline")
        make_alert(
            db_session,
            business,
            alert_type=AlertType.SUPPLIER_RISK,
            severity=AlertSeverity.CRITICAL,
            title="supplier",
            period=None,
            due_date=None,
            context={"supplier_gstin": SUPPLIER_GSTIN_SAME_STATE},
        )
        make_alert(
            db_session,
            business,
            alert_type=AlertType.ITC_AT_RISK,
            severity=AlertSeverity.INFO,
            title="itc",
            period="2026-03",
            due_date=None,
        )

    def test_by_type(self, auth_client, mixed):
        assert titles(listing(auth_client, type="supplier_risk")) == ["supplier"]

    def test_by_severity(self, auth_client, mixed):
        assert titles(listing(auth_client, severity="info")) == ["itc"]

    def test_by_period(self, auth_client, mixed):
        assert titles(listing(auth_client, period="2026-03")) == ["itc"]

    def test_an_unknown_type_is_refused(self, auth_client, mixed):
        assert auth_client.get("/api/v1/alerts", params={"type": "invented"}).status_code == 422

    def test_total_counts_what_matched_the_filter(self, auth_client, mixed):
        page = listing(auth_client, type="supplier_risk")

        assert page["total"] == 1

    def test_the_open_count_ignores_the_filter(self, auth_client, mixed):
        # The badge is about the business, not about the page being looked at.
        page = listing(auth_client, type="supplier_risk")

        assert page["open_total"] == 3


class TestPaging:
    @pytest.fixture()
    def five(self, db_session, business):
        for day in range(1, 6):
            make_alert(db_session, business, due_date=date(2026, 5, day), title=f"day {day}")

    def test_a_page_carries_the_whole_total(self, auth_client, five):
        page = listing(auth_client, limit=2)

        assert titles(page) == ["day 1", "day 2"]
        assert (page["total"], page["limit"], page["offset"]) == (5, 2, 0)

    def test_the_offset_continues_where_the_page_ended(self, auth_client, five):
        assert titles(listing(auth_client, limit=2, offset=2)) == ["day 3", "day 4"]

    def test_the_page_size_is_bounded(self, auth_client):
        assert auth_client.get("/api/v1/alerts", params={"limit": 500}).status_code == 422


class TestMarkingOneAsRead:
    def test_it_becomes_read(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "read"

    def test_it_stays_open(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert listing(auth_client)["open_total"] == 1

    def test_reading_it_twice_changes_nothing(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        again = auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert again.status_code == 200
        assert again.json()["status"] == "read"

    def test_reading_a_dismissed_alert_does_not_reopen_it(
        self, auth_client, db_session, business
    ):
        # A client that renders the closed list and marks rows seen as they
        # scroll past would otherwise undo every dismissal on the screen.
        alert = make_alert(db_session, business, status=AlertStatus.DISMISSED)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert response.json()["status"] == "dismissed"

    def test_reading_a_resolved_alert_leaves_it_resolved(
        self, auth_client, db_session, business
    ):
        alert = make_alert(db_session, business, status=AlertStatus.RESOLVED)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert response.json()["status"] == "resolved"


class TestDismissing:
    def test_it_leaves_the_open_list(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "dismissed"
        assert listing(auth_client)["items"] == []

    def test_it_is_still_there_to_be_found(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        assert len(listing(auth_client, scope="closed")["items"]) == 1

    def test_dismissing_twice_changes_nothing(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        again = auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        assert again.json()["status"] == "dismissed"

    def test_a_read_alert_can_be_dismissed(self, auth_client, db_session, business):
        alert = make_alert(db_session, business, status=AlertStatus.READ)

        assert auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss").json()["status"] == (
            "dismissed"
        )

    def test_a_resolved_alert_is_not_downgraded_to_dismissed(
        self, auth_client, db_session, business
    ):
        # Resolved says the return was filed; dismissed says somebody made the
        # alert go away. Overwriting the first with the second loses the only
        # evidence there is that these alerts do anything.
        alert = make_alert(db_session, business, status=AlertStatus.RESOLVED)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        assert response.json()["status"] == "resolved"


class TestDismissingIsWhatTheSweepRespects:
    """The loop this endpoint exists for, end to end.

    The sweep's rule is that a dismissal is respected. Until there was a way to
    produce a dismissal, that rule could not fire at all — so this is the test
    that the two halves are actually connected.
    """

    @pytest.fixture()
    def established(self, db_session, business) -> Business:
        """The registered tenant, backdated to before the period under test.

        Registration stamps ``created_at`` from the real clock, and the sweep
        deliberately says nothing about periods that closed before a business
        signed up — so without this every sweep below would decline to look at
        2026-04 and would pass while doing nothing at all.
        """
        business.created_at = datetime(2026, 4, 2, 10, 0)
        db_session.commit()
        return business

    def swept(self, db, business, *, today: date) -> list[Alert]:
        alerting.sweep_business(db, business, today=today)
        db.commit()
        return [
            row
            for row in db.query(Alert).filter_by(business_id=business.id).all()
            if (row.context or {}).get("return_type") == ReturnType.GSTR3B.value
        ]

    def raise_and_dismiss(self, auth_client, db_session, business) -> Alert:
        """The alert the sweep itself raises, dismissed the way a business would.

        Swept rather than inserted: an alert built by hand can disagree with
        what the sweep would have computed for the same day — a severity one
        step off is enough to make the next sweep call it an escalation — and a
        test that arranged that would be asserting against its own fixture
        rather than against the rule.
        """
        raised = self.swept(db_session, business, today=date(2026, 5, 14))
        assert len(raised) == 1, "the sweep raised nothing to dismiss"

        response = auth_client.post(f"/api/v1/alerts/{raised[0].id}/dismiss")
        assert response.status_code == 200, response.text
        return raised[0]

    def test_a_dismissed_alert_is_not_raised_again_tomorrow(
        self, auth_client, db_session, established
    ):
        self.raise_and_dismiss(auth_client, db_session, established)

        rows = self.swept(db_session, established, today=date(2026, 5, 15))

        assert len(rows) == 1, "the sweep raised a second copy beside the dismissed one"
        assert rows[0].status is AlertStatus.DISMISSED

    def test_the_deadline_passing_brings_it_back(
        self, auth_client, db_session, established
    ):
        alert = self.raise_and_dismiss(auth_client, db_session, established)

        # Past the 20th: the same return, now genuinely worse than when it was
        # dismissed, which is new information rather than the same reminder.
        self.swept(db_session, established, today=date(2026, 5, 25))
        db_session.refresh(alert)

        assert alert.status is AlertStatus.PENDING
        assert alert.severity is AlertSeverity.CRITICAL


class TestOneTenantCannotTouchAnothers:
    @pytest.fixture()
    def rival_alert(self, db_session, other_tenant) -> Alert:
        rival = db_session.query(Business).filter_by(gstin=SUPPLIER_GSTIN_SAME_STATE).one()
        return make_alert(db_session, rival, title="rival's problem")

    def test_their_alerts_are_not_in_the_listing(self, auth_client, rival_alert):
        assert listing(auth_client, scope="all")["items"] == []

    def test_their_alerts_are_not_in_the_count(self, auth_client, rival_alert):
        assert listing(auth_client)["open_total"] == 0

    def test_reading_one_answers_404_rather_than_403(self, auth_client, rival_alert):
        # 403 would confirm the id exists, which is enough to learn how many
        # alerts a competitor has by counting the ids that answer differently.
        assert auth_client.post(f"/api/v1/alerts/{rival_alert.id}/read").status_code == 404

    def test_dismissing_one_answers_404(self, auth_client, db_session, rival_alert):
        assert auth_client.post(f"/api/v1/alerts/{rival_alert.id}/dismiss").status_code == 404

        db_session.refresh(rival_alert)
        assert rival_alert.status is AlertStatus.PENDING

    def test_an_id_that_does_not_exist_answers_404(self, auth_client):
        assert auth_client.post("/api/v1/alerts/9999/dismiss").status_code == 404


class TestTheAlertIsNotDeliveredAnywhere:
    def test_the_row_says_so(self, auth_client, db_session, business):
        # Asserted rather than assumed: the day a sender exists these become
        # populated, and this is the test that says the contract changed.
        make_alert(db_session, business)

        item = listing(auth_client)["items"][0]

        assert item["channel"] is None
        assert item["sent_at"] is None

    def test_the_alert_says_what_it_is_about(self, auth_client, db_session, business):
        make_alert(db_session, business)

        item = listing(auth_client)["items"][0]

        assert item["alert_type"] == AlertType.FILING_DEADLINE.value
        assert item["period"] == PERIOD
        assert item["due_date"] == GSTR3B_DUE.isoformat()
        assert item["context"]["return_type"] == ReturnType.GSTR3B.value


class TestTheBadgeAgreesWithTheList:
    """The dashboard's ``open_alerts`` and this listing must be one number.

    They were not: the badge counted PENDING and SENT alone, so reading an
    alert took it off the badge while it stayed on the list it links to.
    """

    def badge(self, client) -> int:
        response = client.get("/api/v1/dashboard")
        assert response.status_code == 200, response.text
        return response.json()["open_alerts"]

    def test_reading_an_alert_does_not_change_the_badge(
        self, auth_client, db_session, business
    ):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/read")

        assert self.badge(auth_client) == 1

    def test_dismissing_one_does(self, auth_client, db_session, business):
        alert = make_alert(db_session, business)
        auth_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

        assert self.badge(auth_client) == 0

    def test_the_badge_is_the_listings_open_total(self, auth_client, db_session, business):
        make_alert(db_session, business, title="one")
        make_alert(db_session, business, status=AlertStatus.READ, title="two")
        make_alert(db_session, business, status=AlertStatus.DISMISSED, title="three")

        assert self.badge(auth_client) == listing(auth_client)["open_total"] == 2


class TestAUserActionDoesNotOverwriteTheSweep:
    """The sweep resolves an alert between the route loading it and writing.

    Simulated with a Core UPDATE that leaves the route's loaded row stale, which
    is what a concurrent sweep's commit looks like from inside the request.
    """

    @pytest.fixture
    def resolved_mid_request(self, monkeypatch, db_session):
        from sqlalchemy import update

        from app.routers import alerts as alerts_router

        original = alerts_router._owned_alert

        def load_then_sweep(db, business, alert_id):
            alert = original(db, business, alert_id)
            db.execute(
                update(Alert)
                .where(Alert.id == alert.id)
                .values(status=AlertStatus.RESOLVED)
                .execution_options(synchronize_session=False)
            )
            return alert

        monkeypatch.setattr(alerts_router, "_owned_alert", load_then_sweep)

    @pytest.mark.parametrize("action", ["dismiss", "read"])
    def test_a_resolution_landing_first_stays_resolved(
        self, auth_client, db_session, business, resolved_mid_request, action
    ):
        alert = make_alert(db_session, business, status=AlertStatus.SENT)

        response = auth_client.post(f"/api/v1/alerts/{alert.id}/{action}")

        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        db_session.expire_all()
        assert db_session.get(Alert, alert.id).status is AlertStatus.RESOLVED
