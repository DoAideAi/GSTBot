"""A GSTR-2B with no invoices is a statement, not a wrong file.

The portal issues a 2B to every registration every month. When no supplier
filed anything against the business it holds no documents, and the import
refused it — "No invoices found in the file. Check that this is a GSTR-2B
download" — though it was one. That is the month reconciliation matters most:
every purchase booked is then missing from the statement, and all of its
credit is at risk.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE

IMPORT = "/api/v1/reconciliation/gstr2b/import"
RUN = "/api/v1/reconciliation/run"


def _upload(client, payload, *, period=None, name="2b.json"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    data = {"period": period} if period else {}
    return client.post(IMPORT, files={"file": (name, body, "application/json")}, data=data)


def _nil(**data):
    return {"data": {"gstin": BUSINESS_GSTIN, "rtnprd": "042026", **data}}


def test_a_nil_statement_with_empty_sections_is_imported(auth_client, paid_business):
    response = _upload(auth_client, _nil(docdata={"b2b": [], "cdnr": []}))
    assert response.status_code == 201, response.text
    assert response.json()["period"] == "2026-04"


def test_a_nil_statement_with_no_document_block_is_imported(auth_client, paid_business):
    response = _upload(auth_client, _nil())
    assert response.status_code == 201, response.text


def test_reconciling_against_it_puts_every_booked_purchase_at_risk(
    auth_client, db_session, paid_business
):
    db_session.add(
        Invoice(
            business_id=paid_business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
            invoice_number="P-1",
            invoice_date=date(2026, 4, 10),
            period="2026-04",
            taxable_value=Decimal("1000.00"),
            igst=Decimal("180.00"),
            total_value=Decimal("1180.00"),
        )
    )
    db_session.commit()
    assert _upload(auth_client, _nil(docdata={"b2b": []})).status_code == 201

    run = auth_client.post(RUN, json={"period": "2026-04"})
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["missing_in_2b_count"] == 1
    assert Decimal(body["itc_at_risk"]) == Decimal("180.00")


def test_a_file_with_no_period_and_no_documents_is_still_refused(auth_client, paid_business):
    # Nothing in it says it is a statement, or for which month.
    response = _upload(auth_client, {"data": {"docdata": {"b2b": []}}})
    assert response.status_code == 422
    assert "period" in response.json()["detail"].lower()


def test_junk_json_is_still_refused(auth_client, paid_business):
    assert _upload(auth_client, {"hello": "world"}).status_code == 422


def test_an_empty_statement_with_a_chosen_period_is_imported(auth_client, paid_business):
    response = _upload(auth_client, {"data": {"docdata": {"b2b": []}}}, period="2026-04")
    assert response.status_code == 201, response.text
