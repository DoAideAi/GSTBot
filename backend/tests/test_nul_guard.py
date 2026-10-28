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
