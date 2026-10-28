"""GET /businesses/mine/export — everything held about one business."""
from __future__ import annotations

import json
import logging

from app.models.invoice import Invoice
from app.models.user import UserRole
from app.services import data_export
from tests.conftest import BUSINESS_GSTIN, TEST_EMAIL
from tests.test_invoices import upload
from tests.test_rbac import set_home_role

URL = "/api/v1/businesses/mine/export"


def test_the_export_is_an_attachment_named_for_the_business(auth_client):
    response = auth_client.get(URL)

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert BUSINESS_GSTIN in disposition
    assert response.json()["format_version"] == data_export.FORMAT_VERSION


def test_every_table_that_holds_a_business_row_is_in_it(auth_client):
    """Driven by the registry, so a new table is exported the day it ships —
    and this names the ones that matter, so the registry cannot quietly stop
    finding them."""
    tables = auth_client.get(URL).json()["tables"]
    assert set(tables) == {t.name for t in data_export.exported_tables()}
    assert {
        "invoices", "suppliers", "reconciliation_runs", "gstr_returns", "alerts",
        "report_purchases", "subscriptions", "subscription_payments", "users",
    } <= set(tables)


def test_the_books_are_in_it_with_money_as_strings(auth_client, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    [row] = auth_client.get(URL).json()["tables"]["invoices"]

    assert row["id"] == invoice_id
    assert isinstance(row["taxable_value"], str)
    assert row["raw_text"]


def test_a_deleted_invoice_is_still_in_it_because_it_is_still_held(
    auth_client, sample_invoice_text
):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    assert auth_client.delete(f"/api/v1/invoices/{invoice_id}").status_code == 204

    [row] = auth_client.get(URL).json()["tables"]["invoices"]
    assert row["deleted_at"] is not None


def test_credentials_and_server_paths_are_withheld(auth_client, sample_invoice_text, db_session):
    upload(auth_client, sample_invoice_text)
    stored = db_session.query(Invoice).one().storage_path

    body = auth_client.get(URL).json()
    text = json.dumps(body)

    [user] = body["tables"]["users"]
    assert user["email"] == TEST_EMAIL
    assert "hashed_password" not in user
    assert "oauth_id" not in user
    assert "storage_path" not in body["tables"]["invoices"][0]
    assert stored not in text
    assert "users.hashed_password" in body["withheld"]


def test_another_businesss_rows_are_not_in_it(
    auth_client, client, other_tenant, sample_invoice_text
):
    rival = {"Authorization": f"Bearer {other_tenant}"}
    stored = client.post(
        "/api/v1/invoices/upload",
        files={"file": ("rival.txt", sample_invoice_text.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
        headers=rival,
    )
    assert stored.status_code == 201, stored.text

    body = auth_client.get(URL).json()
    assert body["tables"]["invoices"] == []
    assert "rival@example.com" not in json.dumps(body)


def test_only_the_owner_can_take_the_whole_account(auth_client, db_session):
    set_home_role(db_session, UserRole.ACCOUNTANT)
    assert auth_client.get(URL).status_code == 403


def test_taking_it_leaves_an_audit_line(auth_client, caplog):
    with caplog.at_level(logging.INFO, logger="app.routers.businesses"):
        auth_client.get(URL)
    [line] = [r for r in caplog.records if r.getMessage() == "Account exported"]
    assert line.rows["users"] == 1
