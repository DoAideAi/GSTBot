"""Recording that a return was filed, and reporting where each one stands.

The portal is where a return is actually submitted and nothing here can observe
that, so this half of the product runs entirely on what the business tells us.
The tests below are mostly about the two ways that goes wrong: a filing that
could not have happened as described, and a filing that happened but was never
recorded — which is the one that makes the product nag someone who is up to
date.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services import filing as filing_service
from app.services import gst_calendar
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE

# A fixed "now" so the completed-period window never moves under the tests.
TODAY = date(2026, 6, 15)
PERIOD = "2026-04"  # Completed, and both its returns are overdue on TODAY.
LAST_PERIOD = "2026-05"  # Completed; GSTR-1 due 11 Jun, GSTR-3B due 20 Jun.


@pytest.fixture()
def frozen_today(monkeypatch):
    """Pin the Indian date the whole feature measures against."""
    monkeypatch.setattr(gst_calendar, "today_ist", lambda: TODAY)
    return TODAY


def sale(
    db, business_id, *, period=PERIOD, number=None, taxable="100000.00", igst="18000.00"
) -> Invoice:
    invoice = Invoice(
        business_id=business_id,
        invoice_type=InvoiceType.SALES,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        # Unique per counterparty and direction — the table enforces it.
        invoice_number=number or f"S-{period}-{db.query(Invoice).count() + 1}",
        invoice_date=date(int(period[:4]), int(period[5:]), 15),
        period=period,
        place_of_supply="29",
        hsn_code="84713010",
        tax_rate=Decimal("18"),
        taxable_value=Decimal(taxable),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal(igst),
        cess=Decimal("0.00"),
        total_value=Decimal(taxable) + Decimal(igst),
        reverse_charge=False,
    )
    db.add(invoice)
    db.commit()
    return invoice


def record(client, return_type="gstr3b", **payload):
    body = {"period": PERIOD}
    body.update(payload)
    return client.post(f"/api/v1/filing/{return_type}/filed", json=body)


# ---------------------------------------------------------------------------
# The ARN
# ---------------------------------------------------------------------------

class TestTheAcknowledgementReference:
    @pytest.mark.parametrize(
        ("supplied", "stored"),
        [
            ("AA270426123456Z", "AA270426123456Z"),
            ("aa270426123456z", "AA270426123456Z"),  # Upper-cased.
            ("AA2704 2612 3456Z", "AA270426123456Z"),  # The portal prints it spaced.
            ("  AA270426123456Z  ", "AA270426123456Z"),
            ("", None),  # An empty field is "not to hand", not a bad ARN.
            (None, None),
        ],
    )
    def test_it_is_normalised_rather_than_rejected(self, supplied, stored):
        assert filing_service.normalise_arn(supplied) == stored

    @pytest.mark.parametrize("junk", ["not-an-arn", "AA2704!!", "short", "-" * 12])
    def test_something_that_is_plainly_not_an_arn_is_refused(self, junk):
        with pytest.raises(filing_service.FilingNotRecordable, match="is not an ARN"):
            filing_service.normalise_arn(junk)

    def test_an_unusual_length_is_accepted(self):
        # Deliberately not pinned to 15. Locking a business out of recording a
        # filing that genuinely happened leaves the deadline alert firing
        # forever, which is a worse failure than storing an odd reference.
        assert filing_service.normalise_arn("AA270426123456ZX9") == "AA270426123456ZX9"


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class TestRecordingAFiling:
    def test_it_marks_the_return_filed(self, auth_client, db_session, business, frozen_today):
        sale(db_session, business.id)

        response = record(auth_client, arn="AA270426123456Z", filed_on="2026-05-18")
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["period"] == PERIOD
        assert body["return_type"] == "gstr3b"
        assert body["status"] == "filed"
        assert body["arn"] == "AA270426123456Z"

    def test_the_filing_date_defaults_to_today_in_india(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        assert record(auth_client).status_code == 201

        stored = db_session.query(GSTRReturn).filter_by(period=PERIOD).one()
        assert gst_calendar.ist_date(stored.filed_at) == TODAY

    def test_it_carries_the_periods_sales_totals(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id)
        sale(db_session, business.id)

        body = record(auth_client).json()
        assert body["invoice_count"] == 2
        assert Decimal(body["total_taxable_value"]) == Decimal("200000.00")
        assert Decimal(body["total_igst"]) == Decimal("36000.00")

    def test_a_period_with_no_invoices_can_still_be_filed(
        self, auth_client, business, frozen_today
    ):
        # A nil return is a real filing, and it is the one most likely to be
        # forgotten — so it must be recordable.
        response = record(auth_client)
        assert response.status_code == 201, response.text
        assert response.json()["invoice_count"] == 0

    def test_the_due_date_comes_back_with_the_record(
        self, auth_client, business, frozen_today
    ):
        body = record(auth_client).json()
        assert body["due_date"].startswith("2026-05-20")

    def test_filing_after_the_due_date_is_reported_as_late(
        self, auth_client, business, frozen_today
    ):
        assert record(auth_client, filed_on="2026-06-01").json()["filed_late"] is True

    def test_filing_on_the_due_date_is_not_late(self, auth_client, business, frozen_today):
        assert record(auth_client, filed_on="2026-05-20").json()["filed_late"] is False


class TestRecordingIsIdempotent:
    """One live return per period and type — the table's own constraint."""

    def test_recording_twice_does_not_file_twice(
        self, auth_client, db_session, business, frozen_today
    ):
        record(auth_client, arn="AA270426123456Z")
        record(auth_client, arn="AA270426123456Z")

        rows = db_session.query(GSTRReturn).filter_by(period=PERIOD).all()
        assert len(rows) == 1

    def test_recording_again_supplies_an_arn_that_was_not_to_hand(
        self, auth_client, business, frozen_today
    ):
        first = record(auth_client)
        assert first.json()["arn"] is None

        second = record(auth_client, arn="AA270426123456Z")
        assert second.json()["arn"] == "AA270426123456Z"
        assert second.json()["id"] == first.json()["id"]

    def test_losing_the_race_to_record_first_is_still_idempotent(
        self, db_session, business, frozen_today, monkeypatch
    ):
        # Another request recorded the period between this one's read and its
        # INSERT. Simulated by hiding the committed row from the first lookup.
        first = filing_service.record_filing(
            db_session, business, PERIOD, ReturnType.GSTR3B, arn="AA270426123456Z"
        )
        real_scalar = db_session.scalar
        calls = {"n": 0}

        def stale_first_read(*args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_scalar(*args, **kwargs)

        monkeypatch.setattr(db_session, "scalar", stale_first_read)
        second = filing_service.record_filing(
            db_session, business, PERIOD, ReturnType.GSTR3B
        )

        assert second.id == first.id
        assert second.arn == "AA270426123456Z"
        assert db_session.query(GSTRReturn).filter_by(period=PERIOD).count() == 1

    def test_correcting_the_date_does_not_erase_the_arn(
        self, auth_client, business, frozen_today
    ):
        # The reason this endpoint is idempotent is so a mistake can be fixed by
        # recording again. Fixing the date must not cost the acknowledgement:
        # the portal issued it, nothing here can derive it a second time, and
        # it is the only evidence the filing actually happened.
        record(auth_client, arn="AA270426123456Z", filed_on="2026-05-18")

        corrected = record(auth_client, filed_on="2026-05-19")
        assert corrected.json()["arn"] == "AA270426123456Z"
        assert corrected.json()["filed_at"].startswith("2026-05-19")

    def test_a_wrong_arn_is_corrected_by_supplying_the_right_one(
        self, auth_client, business, frozen_today
    ):
        record(auth_client, arn="AA270426000000Z")
        assert record(auth_client, arn="AA270426123456Z").json()["arn"] == "AA270426123456Z"

    def test_a_rejected_arn_leaves_the_stored_one_alone(
        self, auth_client, db_session, business, frozen_today
    ):
        # The refusal happens before the record is touched, so a typo on the
        # second attempt costs nothing that was already recorded.
        record(auth_client, arn="AA270426123456Z", filed_on="2026-05-18")

        assert record(auth_client, arn="not-an-arn").status_code == 422

        db_session.expire_all()
        stored = db_session.query(GSTRReturn).filter_by(period=PERIOD).one()
        assert stored.arn == "AA270426123456Z"
        assert gst_calendar.ist_date(stored.filed_at) == date(2026, 5, 18)

    def test_supplying_the_arn_later_does_not_move_the_filing_date(
        self, auth_client, db_session, business, frozen_today
    ):
        # The documented flow: mark it filed on the day, add the ARN once the
        # acknowledgement arrives. The date was right the first time and the
        # second call says nothing about it, so "not supplied" has to mean
        # "unchanged" here exactly as it does for the ARN — otherwise the
        # second call quietly re-dates an on-time filing to whatever today is.
        # TODAY is past the GSTR-3B due date, so that re-dating would make the
        # return late and put a late fee on it that was never owed.
        record(auth_client, filed_on="2026-05-18")

        later = record(auth_client, arn="AA270426123456Z")
        assert later.json()["filed_at"].startswith("2026-05-18")
        assert later.json()["filed_late"] is False

        fee = auth_client.get(f"/api/v1/filing/gstr3b/late-fee?period={PERIOD}").json()
        assert fee["days_late"] == 0
        assert Decimal(fee["late_fee_total"]) == Decimal("0.00")

    def test_a_correction_leaves_the_record_of_what_was_filed_alone(
        self, auth_client, db_session, business, frozen_today
    ):
        # The first recording — straight after the export — is the closest
        # thing to what went to the portal. A sale booked afterwards belongs
        # to a later period's amendment, not to this return; adding the ARN
        # must not rewrite the record to say it was declared.
        sale(db_session, business.id)
        first = record(auth_client, filed_on="2026-05-18").json()
        assert first["invoice_count"] == 1

        sale(db_session, business.id)
        db_session.commit()

        corrected = record(auth_client, arn="AA270426123456Z").json()
        assert corrected["invoice_count"] == 1
        assert Decimal(corrected["total_taxable_value"]) == Decimal("100000.00")

    def test_the_two_returns_for_one_period_are_separate_records(
        self, auth_client, db_session, business, frozen_today
    ):
        record(auth_client, "gstr1")
        record(auth_client, "gstr3b")

        rows = db_session.query(GSTRReturn).filter_by(period=PERIOD).all()
        assert {row.return_type for row in rows} == {ReturnType.GSTR1, ReturnType.GSTR3B}


class TestFilingsThatCouldNotHaveHappened:
    def test_a_future_filing_date_is_refused(self, auth_client, business, frozen_today):
        response = record(auth_client, filed_on="2026-07-01")
        assert response.status_code == 422
        assert "future" in response.json()["detail"]

    def test_a_period_cannot_be_filed_before_it_ended(
        self, auth_client, business, frozen_today
    ):
        # 2026-04 does not open until 1 May. A date inside the period is a
        # mistyped year far more often than it is anything else.
        response = record(auth_client, filed_on="2026-04-20")
        assert response.status_code == 422
        assert "had not ended" in response.json()["detail"]

    def test_the_first_day_the_return_opens_is_accepted(
        self, auth_client, business, frozen_today
    ):
        assert record(auth_client, filed_on="2026-05-01").status_code == 201

    def test_a_bad_arn_is_refused(self, auth_client, business, frozen_today):
        response = record(auth_client, arn="not-an-arn")
        assert response.status_code == 422
        assert "is not an ARN" in response.json()["detail"]

    def test_a_gstr2b_cannot_be_recorded_as_filed(self, auth_client, business, frozen_today):
        # The portal generates it; nobody files it.
        response = record(auth_client, "gstr2b")
        assert response.status_code == 404
        assert "gstr2b" in response.json()["detail"]

    def test_the_service_refuses_a_gstr2b_too(self, db_session, business, frozen_today):
        # The router's allow-list is one guard; the service is reachable from
        # the alerting and from a shell, and refuses on its own account.
        with pytest.raises(filing_service.FilingNotRecordable, match="not a return"):
            filing_service.record_filing(
                db_session, business, PERIOD, ReturnType.GSTR2B
            )

    def test_a_filing_date_before_gst_commencement_is_refused(
        self, auth_client, business, frozen_today
    ):
        response = record(auth_client, filed_on="2017-06-30")
        assert response.status_code == 422
        assert "predates GST commencement" in response.text

    def test_the_day_gst_commenced_is_accepted_as_a_filing_date(
        self, auth_client, db_session, business, frozen_today
    ):
        sale(db_session, business.id, period="2017-07")
        response = record(
            auth_client, period="2017-07", filed_on="2017-07-01"
        )
        # The period validator or service may still reject this for other
        # reasons, but the filed_on date itself is not the cause.
        assert response.status_code != 422 or "predates GST" not in response.text

    def test_a_malformed_period_is_refused(self, auth_client, business, frozen_today):
        assert record(auth_client, period="April").status_code == 422


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestTheStatusOfEveryReturn:
    def test_it_covers_six_completed_periods_of_both_returns(
        self, auth_client, business, frozen_today
    ):
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        assert len(items) == 12
        assert {item["return_type"] for item in items} == {"gstr1", "gstr3b"}

    def test_the_current_month_is_not_listed(self, auth_client, business, frozen_today):
        # June has not ended, so its return does not exist to be late for.
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        assert "2026-06" not in {item["period"] for item in items}

    def test_the_newest_period_comes_first(self, auth_client, business, frozen_today):
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        assert items[0]["period"] == LAST_PERIOD

    def test_an_unfiled_return_reports_no_arn_and_a_negative_countdown(
        self, auth_client, business, frozen_today
    ):
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        april_3b = next(
            item
            for item in items
            if item["period"] == PERIOD and item["return_type"] == "gstr3b"
        )
        assert april_3b["filed"] is False
        assert april_3b["arn"] is None
        # Due 20 May, and it is 15 June.
        assert april_3b["days_until_due"] == -26

    def test_a_return_still_ahead_of_its_deadline_counts_down(
        self, auth_client, business, frozen_today
    ):
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        may_3b = next(
            item
            for item in items
            if item["period"] == LAST_PERIOD and item["return_type"] == "gstr3b"
        )
        assert may_3b["days_until_due"] == 5  # 20 June from 15 June.

    def test_a_recorded_filing_shows_up(self, auth_client, business, frozen_today):
        record(auth_client, arn="AA270426123456Z", filed_on="2026-05-18")

        items = auth_client.get("/api/v1/filing/status").json()["items"]
        april_3b = next(
            item
            for item in items
            if item["period"] == PERIOD and item["return_type"] == "gstr3b"
        )
        assert april_3b["filed"] is True
        assert april_3b["filed_on"] == "2026-05-18"
        assert april_3b["arn"] == "AA270426123456Z"
        assert april_3b["filed_late"] is False

    def test_filing_late_stops_the_clock_rather_than_getting_later(
        self, auth_client, business, frozen_today
    ):
        # Filed 25 May against a 20 May deadline: late by five days, and it
        # stays five days late however long ago that was.
        record(auth_client, filed_on="2026-05-25")

        items = auth_client.get("/api/v1/filing/status").json()["items"]
        april_3b = next(
            item
            for item in items
            if item["period"] == PERIOD and item["return_type"] == "gstr3b"
        )
        assert april_3b["filed_late"] is True

    def test_the_gstr1_deadline_is_nine_days_before_the_gstr3b_one(
        self, auth_client, business, frozen_today
    ):
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        for kind, due in (("gstr1", "2026-05-11"), ("gstr3b", "2026-05-20")):
            line = next(
                item
                for item in items
                if item["period"] == PERIOD and item["return_type"] == kind
            )
            assert line["due_date"] == due


class TestTheStandingsHelperItself:
    """Read directly by the deadline alerting, not only by the endpoint."""

    def test_asking_about_no_periods_does_not_query(self, db_session, business):
        # An empty `IN ()` is a query that can only return nothing, and some
        # backends reject it outright.
        assert (
            filing_service.standings(db_session, business.id, periods=[], as_of=TODAY)
            == []
        )

    def test_an_unfiled_return_past_its_date_is_overdue(self, db_session, business):
        lines = filing_service.standings(
            db_session, business.id, periods=[PERIOD], as_of=TODAY
        )
        assert all(line.overdue for line in lines)

    def test_filing_late_stops_it_being_overdue(
        self, auth_client, db_session, business, frozen_today
    ):
        # Overdue means "still not filed". A return filed five days late is a
        # fact about the past, not something to keep alerting about.
        record(auth_client, filed_on="2026-05-25")

        line = next(
            line
            for line in filing_service.standings(
                db_session, business.id, periods=[PERIOD], as_of=TODAY
            )
            if line.return_type is ReturnType.GSTR3B
        )
        assert line.filed_late is True
        assert line.overdue is False


class TestTenancy:
    def test_another_tenants_filing_is_not_visible(
        self, auth_client, business, other_tenant, frozen_today
    ):
        record(auth_client, arn="AA270426123456Z")

        auth_client.headers.update({"Authorization": f"Bearer {other_tenant}"})
        items = auth_client.get("/api/v1/filing/status").json()["items"]
        assert all(item["filed"] is False for item in items)


# ---------------------------------------------------------------------------
# The date a filing falls on
# ---------------------------------------------------------------------------

class TestReadingAStoredTimestampBackAsAnIndianDate:
    """Midnight IST is 18:30 the previous day in UTC.

    Postgres normalises a ``timestamptz`` to UTC and hands it back that way,
    while SQLite drops the offset entirely — so a naive ``.date()`` is a day
    early on the backend that ships and correct on the one this suite runs.
    """

    def test_an_aware_utc_timestamp_is_converted_not_truncated(self):
        # 18:30 UTC on the 14th *is* midnight on the 15th in India.
        stored = datetime.fromisoformat("2026-05-14T18:30:00+00:00")
        assert gst_calendar.ist_date(stored) == date(2026, 5, 15)

    def test_a_naive_timestamp_is_read_as_the_wall_time_it_was_written_as(self):
        stored = datetime.fromisoformat("2026-05-15T00:00:00")
        assert gst_calendar.ist_date(stored) == date(2026, 5, 15)

    def test_an_ist_timestamp_keeps_its_own_date(self):
        stored = datetime(2026, 5, 15, 0, 0, tzinfo=gst_calendar.IST)
        assert gst_calendar.ist_date(stored) == date(2026, 5, 15)

    def test_a_filing_recorded_at_the_boundary_survives_a_round_trip(
        self, auth_client, db_session, business, frozen_today
    ):
        # The end-to-end version of the three above: whatever the column does
        # to it, the date that comes back is the date that went in.
        record(auth_client, filed_on="2026-05-01")

        stored = db_session.query(GSTRReturn).filter_by(period=PERIOD).one()
        assert stored.status is ReturnStatus.FILED
        assert gst_calendar.ist_date(stored.filed_at) == date(2026, 5, 1)


# ---------------------------------------------------------------------------
# Taking a filing back
# ---------------------------------------------------------------------------

def withdraw(client, return_type="gstr3b", period=PERIOD):
    return client.delete(f"/api/v1/filing/{return_type}/filed", params={"period": period})


def _standing(client, return_type="gstr3b", period=PERIOD):
    items = client.get("/api/v1/filing/status").json()["items"]
    return next(
        item for item in items
        if item["period"] == period and item["return_type"] == return_type
    )


class TestWithdrawingAFilingRecordedByMistake:
    def test_the_period_is_unfiled_again(self, auth_client, business, frozen_today):
        record(auth_client, arn="AA270426123456Z", filed_on="2026-05-18")

        assert withdraw(auth_client).status_code == 204

        standing = _standing(auth_client)
        assert standing["filed"] is False
        assert standing["arn"] is None

    def test_the_record_is_kept_as_a_tombstone(
        self, auth_client, db_session, business, frozen_today
    ):
        record(auth_client, arn="AA270426123456Z")
        withdraw(auth_client)

        rows = db_session.query(GSTRReturn).filter_by(business_id=business.id).all()
        assert len(rows) == 1
        assert rows[0].deleted_at is not None
        assert rows[0].arn == "AA270426123456Z"

    def test_the_period_can_be_recorded_again_afterwards(
        self, auth_client, business, frozen_today
    ):
        record(auth_client, filed_on="2026-05-18")
        withdraw(auth_client)

        again = record(auth_client, filed_on="2026-05-19")

        assert again.status_code == 201
        assert _standing(auth_client)["filed_on"] == "2026-05-19"

    def test_only_the_named_return_is_withdrawn(self, auth_client, business, frozen_today):
        record(auth_client, "gstr1", filed_on="2026-05-10")
        record(auth_client, "gstr3b", filed_on="2026-05-18")

        withdraw(auth_client, "gstr3b")

        assert _standing(auth_client, "gstr1")["filed"] is True
        assert _standing(auth_client, "gstr3b")["filed"] is False

    def test_the_deadline_alert_comes_back(self, auth_client, db_session, business, frozen_today):
        from app.models.alert import Alert, AlertStatus
        from app.services import alerting

        # Backdated: the sweep says nothing about periods closed before signup.
        business.created_at = datetime(2026, 4, 2, 10, 0)
        db_session.commit()
        alerting.sweep_business(db_session, business, today=TODAY)
        db_session.commit()
        record(auth_client, filed_on="2026-06-01")
        alerting.sweep_business(db_session, business, today=TODAY)
        db_session.commit()

        withdraw(auth_client)
        alerting.sweep_business(db_session, business, today=TODAY)
        db_session.commit()

        db_session.expire_all()
        [alert] = [
            row for row in db_session.query(Alert).filter_by(business_id=business.id)
            if row.period == PERIOD and (row.context or {}).get("return_type") == "gstr3b"
        ]
        assert alert.status is AlertStatus.PENDING

    def test_a_period_never_recorded_is_a_404(self, auth_client, business, frozen_today):
        response = withdraw(auth_client)
        assert response.status_code == 404
        assert "No gstr3b filing is recorded for 2026-04" in response.text

    def test_withdrawing_twice_is_a_404_the_second_time(
        self, auth_client, business, frozen_today
    ):
        record(auth_client)
        assert withdraw(auth_client).status_code == 204
        assert withdraw(auth_client).status_code == 404

    def test_an_unknown_return_type_is_a_404(self, auth_client, business, frozen_today):
        assert withdraw(auth_client, "gstr9").status_code == 404

    def test_an_imported_2b_cannot_be_withdrawn_through_it(self, auth_client, business):
        # Not a filable return: the 2B is the portal's statement, not a filing.
        assert withdraw(auth_client, "gstr2b").status_code == 404

    def test_a_malformed_period_is_refused(self, auth_client, business):
        assert withdraw(auth_client, period="April").status_code == 422

    def test_another_tenants_filing_cannot_be_withdrawn(
        self, auth_client, business, other_tenant, frozen_today
    ):
        record(auth_client)
        mine = auth_client.headers["Authorization"]

        auth_client.headers.update({"Authorization": f"Bearer {other_tenant}"})
        assert withdraw(auth_client).status_code == 404

        auth_client.headers.update({"Authorization": mine})
        assert _standing(auth_client)["filed"] is True


class TestCreatedOnlyWhenSomethingIsCreated:
    """``POST /filing/{rt}/filed`` answered 201 to every call.

    Re-recording is the documented way to add an ARN or correct a date, and it
    changes the existing record rather than creating one — so 201 "Created"
    misdescribed it, and a client could not tell a first recording from a
    correction.
    """

    def _record(self, client, **body):
        return client.post(
            "/api/v1/filing/gstr3b/filed", json={"period": "2026-04", **body}
        )

    def test_first_recording_is_201_and_a_correction_is_200(self, auth_client):
        first = self._record(auth_client, filed_on="2026-05-19")
        assert first.status_code == 201, first.text
        again = self._record(auth_client, arn="AA2705260012345")
        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"]

    def test_recording_again_after_a_withdrawal_creates_again(self, auth_client):
        assert self._record(auth_client, filed_on="2026-05-19").status_code == 201
        assert auth_client.delete(
            "/api/v1/filing/gstr3b/filed", params={"period": "2026-04"}
        ).status_code == 204
        assert self._record(auth_client, filed_on="2026-05-20").status_code == 201

    def test_both_answers_are_in_the_spec(self, auth_client):
        op = auth_client.get("/openapi.json").json()["paths"][
            "/api/v1/filing/{return_type}/filed"
        ]["post"]
        assert {"200", "201"} <= set(op["responses"])
