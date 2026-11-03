"""A submitted contact request survives in the operator inbox."""
import pytest

from app.models.feedback import Feedback

URL = "/api/v1/feedback/demo"
BODY = {
    "name": "Demo Visitor",
    "firm": "Example & Co",
    "email": "visitor@example.com",
    "volume": "11–50",
    "workflow": "Review invoice mismatches",
}


def test_acknowledgement_means_the_request_is_saved_and_only_admins_can_read_it(
    client, admin_client, db_session, raw_client
):
    response = client.post(URL, json=BODY)
    assert response.status_code == 201
    row = db_session.query(Feedback).one()
    assert response.json() == {"reference": f"DEMO-{row.id}"}
    assert row.email == BODY["email"]
    assert "Example & Co" in row.message
    assert "Review invoice mismatches" in row.message
    assert row.meta == {"feature_area": "demo-request"}
    assert raw_client.get("/api/v1/feedback").status_code == 401
    assert admin_client.get("/api/v1/feedback").json()["items"][0]["id"] == row.id


@pytest.mark.parametrize("field,value", [
    ("name", " \u200b "), ("firm", ""), ("email", "invalid"),
    ("volume", "anything"), ("workflow", "x" * 1001),
    ("website", "https://spam.example"), ("name", "x" * 101),
])
def test_invalid_or_automated_requests_are_not_saved(client, db_session, field, value):
    assert client.post(URL, json={**BODY, field: value}).status_code == 422
    assert db_session.query(Feedback).count() == 0


def test_optional_notes_and_honeypot_can_be_omitted(client, db_session):
    body = {k: v for k, v in BODY.items() if k != "workflow"}
    assert client.post(URL, json=body).status_code == 201
    assert "To discuss" in db_session.query(Feedback).one().message


def test_contact_form_has_its_own_rate_limit(client, rate_limited):
    for _ in range(5):
        assert client.post(URL, json=BODY).status_code == 201
    assert client.post(URL, json=BODY).status_code == 429
