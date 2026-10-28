"""No value reaches the database carrying U+0000.

PostgreSQL refuses NUL in text and in JSON, so on the database production runs
any of these is a failed write and a 500; SQLite stores it, so without this
file the suite would pass over every one. The guard is a before_flush hook in
``app.core.database``, which every ORM write goes through.
"""
from __future__ import annotations

from app.models.business import Business
from app.models.feedback import ClientError, Feedback
from app.models.invoice import Invoice, InvoiceType


def test_the_public_feedback_form_cannot_be_made_to_fail_with_a_nul(client, db_session):
    response = client.post(
        "/api/v1/feedback",
        json={
            "category": "bug",
            "message": "The upload\u0000 button did nothing",
            "page_url": "https://gst.doaide.com/up\u0000load",
        },
    )

    assert response.status_code == 201
    row = db_session.query(Feedback).one()
    assert row.message == "The upload button did nothing"
    assert row.page_url == "https://gst.doaide.com/upload"


def test_a_reported_browser_error_cannot_either(client, db_session):
    response = client.post(
        "/api/v1/feedback/error",
        json={"page": "/invoices", "message": "Type\u0000Error", "stack": "at x\u0000 (a.js:1)"},
    )

    assert response.status_code < 300
    row = db_session.query(ClientError).one()
    assert "\x00" not in row.message + (row.stack or "")


def test_any_orm_write_is_cleaned_in_text_and_in_nested_json(auth_client, db_session, business):
    invoice = Invoice(
        business_id=business.id,
        invoice_type=InvoiceType.PURCHASE,
        raw_text="Inv\x00oice",
        extraction={"items": [{"description": "Ch\x00air"}]},
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)

    assert invoice.raw_text == "Invoice"
    assert invoice.extraction == {"items": [{"description": "Chair"}]}


def test_a_value_without_nul_is_left_exactly_as_it_was(db_session, auth_client, business):
    business.legal_name = "Umang\tTraders ‮"
    db_session.commit()
    db_session.refresh(business)
    assert business.legal_name == "Umang\tTraders ‮"
    assert isinstance(db_session.get(Business, business.id), Business)


class TestNonFiniteFloatsInJson:
    """P16 M5: NaN and ±Infinity are the other values Postgres refuses inside
    JSON and SQLite stores. ``json.loads`` accepts the tokens and reads ``1e400``
    as infinity, so they arrive in a model's line items and Jev's probabilities.
    The same hook replaces them with ``null``."""

    def test_an_orm_write_replaces_them_at_any_depth(self, auth_client, db_session, business):
        import json

        invoice = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            extraction={
                "line_items": [{"quantity": float("nan"), "amount": float("inf"), "rate": 5.5}],
                "jev": {"probabilities": {"b2b": float("-inf")}},
            },
        )
        db_session.add(invoice)
        db_session.commit()
        db_session.refresh(invoice)

        assert invoice.extraction == {
            "line_items": [{"quantity": None, "amount": None, "rate": 5.5}],
            "jev": {"probabilities": {"b2b": None}},
        }
        json.dumps(invoice.extraction, allow_nan=False)  # what Postgres would accept

    def test_a_model_reply_with_them_in_its_line_items_still_parses(
        self, auth_client, db_session, stub_openrouter, sample_invoice_text
    ):
        import json

        stub_openrouter.update(
            {
                "invoice_number": "INV-9",
                "invoice_date": "2026-04-15",
                "taxable_value": 100,
                "igst": 18,
                "total_value": 118,
                "line_items": [{"description": "Chair", "quantity": float("nan"), "amount": 1e400}],
            }
        )
        response = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("bill.txt", sample_invoice_text.encode(), "text/plain")},
            data={"invoice_type": "purchase"},
        )
        assert response.status_code == 201, response.text
        invoice = db_session.get(Invoice, response.json()["invoice"]["id"])
        json.dumps(invoice.extraction, allow_nan=False)


class TestNulNeverReachesAQueryParameter:
    """P16 M6: psycopg refuses to bind a string holding U+0000, so a NUL in
    anything a query compares against was a DataError and a 500 on Postgres —
    the public sign-in first among them, whose ``username`` is matched against
    ``users.email`` unvalidated. SQLite binds it, so the suite needs to observe
    the stripping rather than the failure."""

    def test_the_sign_in_matches_as_if_the_nul_were_not_there(self, client):
        from tests.conftest import TEST_EMAIL, TEST_PASSWORD
        from tests.test_end_to_end import register

        register(client)
        local, domain = TEST_EMAIL.split("@")
        response = client.post(
            "/api/v1/auth/login",
            data={"username": f"{local}\x00@{domain}", "password": TEST_PASSWORD},
        )
        # Without the hook SQLite compares the NUL and finds nobody: a 401.
        assert response.status_code == 200, response.text

    def test_a_sign_in_that_is_only_garbage_is_refused_not_a_500(self, raw_client):
        response = raw_client.post(
            "/api/v1/auth/login", data={"username": "\x00\x00", "password": "x" * 12}
        )
        assert response.status_code in (400, 401, 422)

    def test_every_parameter_shape_is_cleaned(self):
        from app.core.database import without_nul_params

        assert without_nul_params({"a": "x\x00y", "b": 1}) == {"a": "xy", "b": 1}
        assert without_nul_params(("x\x00", b"\x00", None)) == ("x", b"\x00", None)
        assert without_nul_params([("a\x00",), ("b",)]) == [("a",), ("b",)]
        assert without_nul_params([{"a": "\x00"}]) == [{"a": ""}]
        assert without_nul_params(["a\x00", 2]) == ["a", 2]
        assert without_nul_params(None) is None
