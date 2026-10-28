"""The feedback widget's endpoint and the admin inbox that reads it."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.models.feedback import Feedback, FeedbackCategory
from tests.conftest import TEST_EMAIL

URL = "/api/v1/feedback"


def send(client, **overrides):
    body = {
        "category": "bug",
        "message": "The HSN search returns nothing for 'laptop'.",
        "email": "visitor@example.com",
        "page_url": "https://gst.doaide.com/hsn-code-finder",
        **overrides,
    }
    return client.post(URL, json=body, headers={"User-Agent": "pytest-browser/1.0"})


@pytest.fixture()
def admin(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", f"someone@else.com, {TEST_EMAIL.upper()}")
    return auth_client


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------

class TestAnyoneCanSendFeedback:
    def test_a_visitor_with_no_account_is_heard(self, client, db_session):
        response = send(client)
        assert response.status_code == 201, response.text

        row = db_session.query(Feedback).one()
        assert row.category is FeedbackCategory.BUG
        assert row.message == "The HSN search returns nothing for 'laptop'."
        assert row.email == "visitor@example.com"
        assert row.page_url == "https://gst.doaide.com/hsn-code-finder"

    def test_the_server_records_who_sent_it_rather_than_trusting_the_body(
        self, client, db_session
    ):
        send(client)
        row = db_session.query(Feedback).one()
        assert row.user_agent == "pytest-browser/1.0"
        assert row.ip_address  # the test client's address

    def test_the_body_cannot_supply_the_address_or_agent(self, client):
        assert send(client, ip_address="1.2.3.4").status_code == 422
        assert send(client, user_agent="forged").status_code == 422

    def test_the_email_is_optional_and_a_blank_box_is_no_email(self, client, db_session):
        assert send(client, email="").status_code == 201
        body = {"message": "Love the calculator."}
        assert client.post(URL, json=body).status_code == 201
        assert [row.email for row in db_session.query(Feedback)] == [None, None]

    def test_an_unspecified_category_is_general(self, client, db_session):
        client.post(URL, json={"message": "Nice."})
        assert db_session.query(Feedback).one().category is FeedbackCategory.GENERAL

    @pytest.mark.parametrize("message", ["", "   \n\t "])
    def test_a_blank_message_is_refused(self, client, message):
        assert send(client, message=message).status_code == 422

    def test_a_message_is_stored_trimmed(self, client, db_session):
        send(client, message="  spaced out  ")
        assert db_session.query(Feedback).one().message == "spaced out"

    @pytest.mark.parametrize(
        "field, value",
        [
            ("category", "complaint"),
            ("email", "not-an-email"),
            ("message", "x" * 5001),
            ("page_url", "https://x/" + "a" * 2048),
        ],
    )
    def test_a_malformed_field_is_refused(self, client, field, value):
        assert send(client, **{field: value}).status_code == 422

    def test_markup_is_stored_as_text_not_interpreted(self, client, db_session):
        send(client, message="<script>alert(1)</script>")
        assert db_session.query(Feedback).one().message == "<script>alert(1)</script>"


def test_five_an_hour_from_one_address_then_refused(client, rate_limited):
    for _ in range(5):
        assert send(client).status_code == 201
    blocked = send(client)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _seed(db_session, category, message, when):
    db_session.add(
        Feedback(category=category, message=message, created_at=when, ip_address="10.0.0.1")
    )
    db_session.commit()


class TestOnlyAdminsCanReadIt:
    def test_a_visitor_is_asked_to_sign_in(self, client):
        assert client.get(URL).status_code == 401

    def test_a_signed_in_user_who_is_not_an_admin_is_refused(self, auth_client, monkeypatch):
        # Every user owns a business; owning one does not make you an operator.
        monkeypatch.setattr(settings, "admin_emails", "ops@doaide.com")
        assert auth_client.get(URL).status_code == 403

    def test_with_no_admins_configured_nobody_can_read(self, auth_client, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", "")
        assert auth_client.get(URL).status_code == 403

    def test_an_admin_reads_it_case_insensitively(self, admin):
        assert admin.get(URL).status_code == 200


class TestTheInbox:
    @pytest.fixture()
    def seeded(self, db_session):
        _seed(db_session, FeedbackCategory.BUG, "old bug", datetime(2026, 9, 1, 12, tzinfo=UTC))
        _seed(db_session, FeedbackCategory.FEATURE, "a wish", datetime(2026, 10, 5, 9, tzinfo=UTC))
        _seed(db_session, FeedbackCategory.BUG, "new bug", datetime(2026, 10, 20, 23, tzinfo=UTC))

    def test_newest_first(self, admin, seeded):
        body = admin.get(URL).json()
        assert [i["message"] for i in body["items"]] == ["new bug", "a wish", "old bug"]
        assert body["total"] == 3

    def test_filtered_by_category(self, admin, seeded):
        body = admin.get(URL, params={"category": "bug"}).json()
        assert [i["message"] for i in body["items"]] == ["new bug", "old bug"]
        assert body["total"] == 2

    def test_filtered_by_dates_inclusive_of_both_ends(self, admin, seeded):
        body = admin.get(URL, params={"since": "2026-10-05", "until": "2026-10-20"}).json()
        assert [i["message"] for i in body["items"]] == ["new bug", "a wish"]

    def test_a_range_running_backwards_is_refused(self, admin):
        backwards = {"since": "2026-10-20", "until": "2026-10-01"}
        assert admin.get(URL, params=backwards).status_code == 422

    def test_the_last_representable_day_is_not_a_crash(self, admin, seeded):
        assert admin.get(URL, params={"until": "9999-12-31"}).json()["total"] == 3

    def test_paged(self, admin, seeded):
        body = admin.get(URL, params={"limit": 1, "offset": 1}).json()
        assert [i["message"] for i in body["items"]] == ["a wish"]
        assert body["total"] == 3

    def test_an_unknown_category_filter_is_refused(self, admin):
        assert admin.get(URL, params={"category": "nope"}).status_code == 422


# ---------------------------------------------------------------------------
# What the widget observed about the visit
# ---------------------------------------------------------------------------

METADATA = {
    "pages": ["/", "/gstin-validator"],
    "feature_area": "GSTIN Lookup",
    "time_on_page_ms": 192_000,
    "scroll_depth_pct": 80,
    "click_count": 14,
    "rage_clicks": 5,
    "rage_click_targets": ["button#validate"],
    "form_abandoned": True,
    "form_time_ms": 150_000,
    "js_errors": 1,
    "js_error_messages": ["TypeError: x is undefined"],
    "reloaded": False,
}


class TestTheVisitTravelsWithTheFeedback:
    def test_it_is_stored_and_read_back(self, client, admin, db_session, monkeypatch):
        assert send(client, metadata=METADATA).status_code == 201
        assert db_session.query(Feedback).one().meta == METADATA

        item = admin.get(URL).json()["items"][0]
        assert item["metadata"] == METADATA

    def test_feedback_without_it_still_goes_through(self, client, admin):
        send(client)
        assert admin.get(URL).json()["items"][0]["metadata"] is None

    def test_a_field_this_server_does_not_know_is_dropped_not_refused(self, client, db_session):
        # A newer widget must not cost the visitor their feedback.
        response = send(client, metadata={"scroll_depth_pct": 50, "from_the_future": 1})
        assert response.status_code == 201
        assert db_session.query(Feedback).one().meta == {"scroll_depth_pct": 50}

    @pytest.mark.parametrize(
        "metadata",
        [
            {"scroll_depth_pct": 101},
            {"time_on_page_ms": -1},
            {"pages": ["/x"] * 51},
            {"js_error_messages": ["y" * 301]},
            {"feature_area": "z" * 61},
        ],
    )
    def test_it_is_bounded(self, client, metadata):
        assert send(client, metadata=metadata).status_code == 422


# ---------------------------------------------------------------------------
# Uncaught errors, reported by the browser on its own
# ---------------------------------------------------------------------------

ERROR_URL = "/api/v1/feedback/error"


def report(client, **overrides):
    body = {
        "page": "https://gst.doaide.com/gstin-validator",
        "message": "TypeError: Cannot read properties of undefined (reading 'state')",
        "stack": "at validate (index-abc.js:1:2)",
        **overrides,
    }
    return client.post(ERROR_URL, json=body, headers={"User-Agent": "pytest-browser/1.0"})


class TestUncaughtErrors:
    def test_anyone_can_report_one(self, client, db_session):
        from app.models.feedback import ClientError

        response = report(client)
        assert response.status_code == 200, response.text
        assert response.json() == {"occurrences": 1}
        row = db_session.query(ClientError).one()
        assert row.page == "https://gst.doaide.com/gstin-validator"
        assert row.stack == "at validate (index-abc.js:1:2)"
        assert row.user_agent == "pytest-browser/1.0"

    def test_the_same_error_on_the_same_page_is_counted_not_repeated(self, client, db_session):
        from app.models.feedback import ClientError

        report(client)
        report(client)
        assert report(client).json() == {"occurrences": 3}
        assert db_session.query(ClientError).count() == 1

    def test_the_query_and_fragment_are_not_part_of_the_page(self, client, db_session):
        from app.models.feedback import ClientError

        report(client, page="https://gst.doaide.com/gstin-validator?gstin=27AAPFU0939F1ZV")
        assert report(client, page="https://gst.doaide.com/gstin-validator#token=x").json() == {
            "occurrences": 2
        }
        assert db_session.query(ClientError).one().page == "https://gst.doaide.com/gstin-validator"

    def test_a_different_message_or_page_is_a_different_error(self, client, db_session):
        from app.models.feedback import ClientError

        report(client)
        report(client, message="ReferenceError: y is not defined")
        report(client, page="https://gst.doaide.com/hsn-code-finder")
        assert db_session.query(ClientError).count() == 3

    @pytest.mark.parametrize(
        "field, value",
        [("message", ""), ("page", ""), ("stack", "s" * 10_001), ("message", "m" * 2001)],
    )
    def test_it_is_bounded(self, client, field, value):
        assert report(client, **{field: value}).status_code == 422

    def test_a_flood_from_one_address_is_cut_off(self, client, rate_limited):
        for i in range(30):
            assert report(client, message=f"Error {i}").status_code == 200
        assert report(client, message="Error 31").status_code == 429
