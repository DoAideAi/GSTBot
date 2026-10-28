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
        assert admin.get(URL, params={"since": "2026-10-20", "until": "2026-10-01"}).status_code == 422

    def test_the_last_representable_day_is_not_a_crash(self, admin, seeded):
        assert admin.get(URL, params={"until": "9999-12-31"}).json()["total"] == 3

    def test_paged(self, admin, seeded):
        body = admin.get(URL, params={"limit": 1, "offset": 1}).json()
        assert [i["message"] for i in body["items"]] == ["a wish"]
        assert body["total"] == 3

    def test_an_unknown_category_filter_is_refused(self, admin):
        assert admin.get(URL, params={"category": "nope"}).status_code == 422
