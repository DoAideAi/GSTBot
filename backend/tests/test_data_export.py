"""GET /businesses/mine/export — everything held about one business."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.database import Base
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
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


# ---------------------------------------------------------------------------
# Streamed, not assembled
# ---------------------------------------------------------------------------

def _invoices(db, business_id, count, *, text_kb=0):
    for n in range(count):
        db.add(
            Invoice(
                business_id=business_id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PARSED,
                invoice_number=f"EXP-{n}",
                raw_text="x" * (text_kb * 1024) or None,
            )
        )
    db.commit()


def _assembled(db, business, exported_at):
    """What the export was before it streamed: every row in hand, then rendered."""
    own = Base.metadata.tables["businesses"]
    profile = db.execute(
        select(*[c for c in own.columns if (own.name, c.name) not in data_export.WITHHELD])
        .where(own.c.id == business.id)
    ).one()

    def rows(table):
        cols = [c for c in table.columns if (table.name, c.name) not in data_export.WITHHELD]
        order = [table.c.id] if "id" in table.c else []
        result = db.execute(
            select(*cols).where(table.c.business_id == business.id).order_by(*order)
        )
        return [{k: data_export._value(v) for k, v in r._mapping.items()} for r in result]

    return {
        "format_version": data_export.FORMAT_VERSION,
        "exported_at": exported_at.isoformat(),
        "business": {k: data_export._value(v) for k, v in profile._mapping.items()},
        "tables": {t.name: rows(t) for t in data_export.exported_tables()},
        "withheld": sorted(f"{t}.{c}" for t, c in data_export.WITHHELD),
    }


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 6, 7])
def test_batch_boundaries_join_into_the_same_document(db_session, business, monkeypatch, count):
    # Three rows a batch, so every comma rule is crossed: none, one partial
    # batch, exactly one batch, one and a bit, exactly two, two and a bit.
    monkeypatch.setattr(data_export, "_BATCH_ROWS", 3)
    _invoices(db_session, business.id, count)
    at = datetime(2026, 10, 29, tzinfo=UTC)

    streamed = "".join(data_export.iter_export(db_session, business, exported_at=at))

    assert json.loads(streamed) == _assembled(db_session, business, at)
    assert len(json.loads(streamed)["tables"]["invoices"]) == count


def test_no_piece_holds_more_than_a_batch(db_session, business, monkeypatch):
    # Thirty invoices with 20 KB of OCR text each: assembled, the document was
    # held whole; streamed, the largest piece is one batch.
    monkeypatch.setattr(data_export, "_BATCH_ROWS", 5)
    _invoices(db_session, business.id, 30, text_kb=20)
    counts: dict[str, int] = {}

    pieces = list(
        data_export.iter_export(
            db_session, business, exported_at=datetime.now(UTC), counts=counts
        )
    )

    total = sum(len(p) for p in pieces)
    assert max(len(p) for p in pieces) < 6 * 21 * 1024 < total / 4
    assert counts["invoices"] == 30


def test_the_download_is_streamed_and_complete(auth_client, db_session, business, monkeypatch):
    monkeypatch.setattr(data_export, "_BATCH_ROWS", 4)
    _invoices(db_session, business.id, 10)

    response = auth_client.get(URL)

    assert response.status_code == 200
    assert "content-length" not in response.headers  # chunked, not rendered whole
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert [r["invoice_number"] for r in response.json()["tables"]["invoices"]] == [
        f"EXP-{n}" for n in range(10)
    ]
