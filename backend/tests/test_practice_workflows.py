"""Complete CA workflows and their tenant, quota and concurrency boundaries."""

import csv
import io
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.mixins import utcnow
from app.models.practice import BusinessInvitation, FindingReviewEvent, RegisterImport
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.models.user import User
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, TEST_PASSWORD

API = "/api/v1"


def register_csv(numbers=("IMP-1", "IMP-2")):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Invoice Number",
            "Invoice Date",
            "Supplier GSTIN",
            "Taxable Value",
            "IGST",
            "Total Value",
            "ITC Eligible",
        ]
    )
    for number in numbers:
        writer.writerow(
            [number, "2026-04-15", SUPPLIER_GSTIN_OTHER_STATE, "1000", "180", "1180", "yes"]
        )
    return output.getvalue().encode()


def preview(client, content=None, **data):
    return client.post(
        API + "/register-imports/preview",
        files={"file": ("register.csv", content or register_csv(), "text/csv")},
        data=data,
    )


@pytest.fixture()
def completed(db_session, business):
    run = ReconciliationRun(
        business_id=business.id,
        period="2026-04",
        status=ReconciliationStatus.COMPLETED,
        completed_at=utcnow(),
        total_invoices=2,
        report={
            "findings": [
                {
                    "invoice_number": "A",
                    "category": "matched",
                    "books": {"total_tax": "180"},
                    "gstr2b": {"total_tax": "180"},
                },
                {"invoice_number": "B", "category": "missing_in_2b", "books": {"total_tax": "180"}},
            ]
        },
    )
    db_session.add(run)
    db_session.commit()
    return run


def other_user(client, email="reviewer@example.com"):
    response = client.post(
        API + "/auth/register",
        json={"email": email, "password": TEST_PASSWORD, "full_name": "Reviewer"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_preview_creates_no_invoices_then_imports_distinct_rows_once(auth_client, db_session):
    response = preview(auth_client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ready"] == 2 and data["invalid"] == 0
    assert list(db_session.scalars(select(Invoice))) == []
    url = API + f'/register-imports/{data["id"]}/commit'
    result = auth_client.post(url, json={"save_mapping_name": "Monthly purchases"})
    assert result.status_code == 200, result.text
    assert result.json()["imported"] == 2
    assert auth_client.post(url, json={}).json() == result.json()
    invoices = list(db_session.scalars(select(Invoice).order_by(Invoice.id)))
    assert [i.invoice_number for i in invoices] == ["IMP-1", "IMP-2"]
    assert all(i.period == "2026-04" and i.itc_eligible for i in invoices)
    assert (
        auth_client.get(API + "/register-imports/mappings").json()["items"][0]["name"]
        == "Monthly purchases"
    )
    assert preview(auth_client).json()["duplicates"] == 2


def test_duplicate_groups_are_never_silently_collapsed(auth_client):
    data = preview(auth_client, register_csv(("DUP", "DUP"))).json()
    assert data["invalid"] == 2 and data["ready"] == 0
    assert (
        auth_client.post(API + f'/register-imports/{data["id"]}/commit', json={}).status_code == 422
    )


def test_import_requires_explicit_skipping(auth_client):
    data = preview(auth_client, register_csv(("A", "=SUM(A1)"))).json()
    assert data["invalid"] == 1
    url = API + f'/register-imports/{data["id"]}/commit'
    assert auth_client.post(url, json={}).status_code == 422
    result = auth_client.post(url, json={"skip_invalid": True})
    assert result.status_code == 200, result.text
    assert result.json()["imported"] == 1 and result.json()["invalid_skipped"] == 1


def test_import_respects_the_monthly_cap_atomically(auth_client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=1")
    data = preview(auth_client).json()
    response = auth_client.post(API + f'/register-imports/{data["id"]}/commit', json={})
    assert response.status_code == 402, response.text
    assert list(db_session.scalars(select(Invoice))) == []


def test_expired_or_foreign_preview_cannot_be_committed(auth_client, client, db_session):
    data = preview(auth_client).json()
    headers = other_user(client)
    url = API + f'/register-imports/{data["id"]}/commit'
    assert client.post(url, json={}, headers=headers).status_code == 404
    batch = db_session.get(RegisterImport, data["id"])
    batch.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert auth_client.post(url, json={}).status_code == 409


def test_xlsx_formulas_are_errors_and_date_cells_are_supported(auth_client):
    from datetime import date

    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Invoice Number", "Invoice Date", "Supplier GSTIN", "Taxable Value"])
    sheet.append(["A", date(2026, 4, 15), SUPPLIER_GSTIN_OTHER_STATE, "=1+2"])
    body = io.BytesIO()
    workbook.save(body)
    response = auth_client.post(
        API + "/register-imports/preview",
        files={"file": ("register.xlsx", body.getvalue(), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["invalid"] == 1
    assert response.json()["rows"][0]["data"]["invoice_date"] == "2026-04-15"


def test_invitation_is_email_bound_single_use_and_revocable(auth_client, client, db_session):
    headers = other_user(client)
    result = auth_client.post(
        API + "/invitations", json={"email": "reviewer@example.com", "role": "viewer"}
    )
    assert result.status_code == 201, result.text
    invite = result.json()
    assert db_session.get(BusinessInvitation, invite["id"]).token_hash != invite["token"]
    assert (
        auth_client.post(API + "/invitations/accept", json={"token": invite["token"]}).status_code
        == 403
    )
    accepted = client.post(
        API + "/invitations/accept", json={"token": invite["token"]}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    assert (
        client.post(
            API + "/invitations/accept", json={"token": invite["token"]}, headers=headers
        ).status_code
        == 404
    )
    membership = auth_client.get(API + "/businesses/mine/members").json()["items"][0]
    switched = {**headers, "X-Business-Id": str(accepted.json()["business_id"])}
    assert client.get(API + "/auth/me", headers=switched).json()["active_role"] == "viewer"
    assert (
        client.post(
            API + "/register-imports/preview",
            headers=switched,
            files={"file": ("r.csv", register_csv(), "text/csv")},
        ).status_code
        == 403
    )
    assert (
        auth_client.patch(
            API + f'/invitations/members/{membership["id"]}', json={"role": "accountant"}
        ).status_code
        == 200
    )
    assert client.get(API + "/auth/me", headers=switched).json()["active_role"] == "accountant"
    assert (
        auth_client.delete(API + f'/businesses/mine/members/{membership["id"]}').status_code == 204
    )
    assert client.get(API + "/auth/me", headers=switched).status_code == 403


def test_revoked_expired_and_owner_lost_invites_cannot_grant_access(
    auth_client, client, db_session
):
    for kind in ["revoked", "expired", "owner_lost"]:
        invite = auth_client.post(
            API + "/invitations", json={"email": "new@example.com", "role": "accountant"}
        ).json()
        stored = db_session.get(BusinessInvitation, invite["id"])
        if kind == "revoked":
            auth_client.delete(API + f'/invitations/{invite["id"]}')
        elif kind == "expired":
            stored.expires_at = utcnow() - timedelta(seconds=1)
            db_session.commit()
        else:
            db_session.get(User, stored.created_by).is_active = False
            db_session.commit()
        assert (
            client.post(API + "/invitations/inspect", json={"token": invite["token"]}).status_code
            == 404
        )


def test_new_invited_account_needs_no_gstin(auth_client, client):
    invite = auth_client.post(
        API + "/invitations", json={"email": "reviewer@example.com", "role": "accountant"}
    ).json()
    headers = other_user(client)
    assert (
        client.post(
            API + "/invitations/accept", json={"token": invite["token"]}, headers=headers
        ).status_code
        == 200
    )
    businesses = client.get(API + "/businesses/mine", headers=headers)
    assert businesses.status_code == 200, businesses.text
    assert len(businesses.json()["items"]) == 2


def test_review_requires_evidence_and_protects_concurrent_edits(auth_client, db_session, completed):
    url = API + f"/practice/runs/{completed.id}"
    assert auth_client.get(url).status_code == 200
    assert auth_client.post(url + "/approve").status_code == 409
    payload = {"version": 0, "status": "resolved", "decision": "accept_match", "note": ""}
    assert auth_client.patch(url + "/findings/1", json=payload).status_code == 422
    payload["note"] = "Source evidence checked; supplier follow-up documented."
    response = auth_client.patch(url + "/findings/1", json=payload)
    assert response.status_code == 200, response.text
    assert auth_client.patch(url + "/findings/1", json=payload).status_code == 409
    assert len(list(db_session.scalars(select(FindingReviewEvent)))) == 1
    assert auth_client.get(url).json()["unresolved"] == 0
    assert auth_client.post(url + "/approve").status_code == 200
    payload.update(version=1, status="in_review", decision="follow_up")
    assert auth_client.patch(url + "/findings/1", json=payload).status_code == 200
    assert auth_client.get(url).json()["approved"] is False


def test_review_cannot_assign_an_outsider_or_read_a_foreign_run(auth_client, client, completed):
    headers = other_user(client)
    outsider = client.get(API + "/auth/me", headers=headers).json()["id"]
    url = API + f"/practice/runs/{completed.id}"
    assert client.get(url, headers=headers).status_code == 404
    result = auth_client.patch(
        url + "/findings/1",
        json={"version": 0, "status": "in_review", "decision": "none", "assignee_id": outsider},
    )
    assert result.status_code == 422
    portfolio = client.get(API + "/practice/clients?period=2026-04", headers=headers).json()
    assert all(item["run_id"] != completed.id for item in portfolio["items"])


def test_new_source_data_blocks_old_approval_and_review(
    auth_client, db_session, business, completed
):
    db_session.add(
        Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            period=completed.period,
            updated_at=utcnow() + timedelta(seconds=1),
        )
    )
    db_session.commit()
    url = API + f"/practice/runs/{completed.id}"
    assert auth_client.get(url).json()["stale"] is True
    assert auth_client.post(url + "/approve").status_code == 409
    assert (
        auth_client.patch(
            url + "/findings/1", json={"version": 0, "status": "in_review", "decision": "none"}
        ).status_code
        == 409
    )


def test_reviewed_export_completes_onboarding_and_preserves_original_finding(
    auth_client, completed
):
    pilot = auth_client.post(API + "/subscriptions/pilot", json={"tier": "enterprise"})
    assert pilot.status_code == 200, pilot.text
    url = API + f"/practice/runs/{completed.id}"
    assert (
        auth_client.patch(
            url + "/findings/1",
            json={
                "version": 0,
                "status": "resolved",
                "decision": "accept_match",
                "note": "=Do not execute this as a spreadsheet formula",
            },
        ).status_code
        == 200
    )
    assert auth_client.post(url + "/approve").status_code == 200
    response = auth_client.get(url + "/export.csv")
    assert response.status_code == 200, response.text
    assert "'=Do not execute" in response.text
    assert "missing_in_2b" in response.text
    assert (
        auth_client.get(API + "/dashboard?period=2026-04").json()["reviewed_report_exported"]
        is True
    )


def test_disputing_a_matched_finding_blocks_report_completion(auth_client, completed):
    url = API + f"/practice/runs/{completed.id}"
    for index, decision, status in [
        (1, "accept_match", "resolved"),
        (0, "reject_match", "in_review"),
    ]:
        result = auth_client.patch(
            url + f"/findings/{index}",
            json={
                "version": 0,
                "status": status,
                "decision": decision,
                "note": "Checked the source documents.",
            },
        )
        assert result.status_code == 200, result.text
    assert auth_client.get(url).json()["unresolved"] == 1
    assert auth_client.post(url + "/approve").status_code == 409
    assert (
        auth_client.patch(
            url + "/findings/0",
            json={
                "version": 1,
                "status": "resolved",
                "decision": "reject_match",
                "note": "Wrong match",
            },
        ).status_code
        == 422
    )


def test_reissuing_an_invitation_invalidates_the_older_grant(auth_client):
    body = {"email": "reviewer@example.com", "role": "accountant"}
    old = auth_client.post(API + "/invitations", json=body).json()
    new = auth_client.post(API + "/invitations", json={**body, "role": "viewer"}).json()
    assert (
        auth_client.post(API + "/invitations/inspect", json={"token": old["token"]}).status_code
        == 404
    )
    assert (
        auth_client.post(API + "/invitations/inspect", json={"token": new["token"]}).json()["role"]
        == "viewer"
    )


def test_purchase_import_to_reviewed_export_uses_real_reconciliation(auth_client):
    import json

    from tests.test_gstr2b import portal_json

    assert (
        auth_client.post(API + "/subscriptions/pilot", json={"tier": "enterprise"}).status_code
        == 200
    )
    draft = preview(auth_client).json()
    committed = auth_client.post(API + f'/register-imports/{draft["id"]}/commit', json={})
    assert committed.status_code == 200, committed.text
    statement = portal_json()
    invoice = statement["data"]["docdata"]["b2b"][0]["inv"][0]
    invoice.update(inum="IMP-1", val=1180)
    invoice["items"][0].update(txval=1000, igst=180)
    imported = auth_client.post(
        API + "/reconciliation/gstr2b/import",
        files={
            "file": ("2b.json", json.dumps(statement).encode(), "application/json"),
        },
    )
    assert imported.status_code == 201, imported.text
    result = auth_client.post(API + "/reconciliation/run", json={"period": "2026-04"})
    assert result.status_code == 201, result.text
    url = API + f'/practice/runs/{result.json()["id"]}'
    report = auth_client.get(url).json()
    assert report["stale"] is False and report["unresolved"] == 1
    categories = {row["category"] for row in report["findings"]}
    assert categories == {"matched", "missing_in_2b"}
    index = next(i for i, f in enumerate(report["findings"]) if f["category"] == "missing_in_2b")
    saved = auth_client.patch(
        url + f"/findings/{index}",
        json={
            "version": 0,
            "status": "resolved",
            "decision": "accept_match",
            "note": "Confirmed absent from the supplied statement; hold its credit.",
        },
    )
    assert saved.status_code == 200, saved.text
    assert auth_client.post(url + "/approve").status_code == 200
    exported = auth_client.get(url + "/export.csv")
    assert exported.status_code == 200, exported.text
    assert "180.00" in exported.text and "IMP-2" in exported.text
    assert auth_client.get(API + "/dashboard?period=2026-04").json()["reviewed_report_exported"]


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("Invoice Date", "2026-02-30", "date"),
        ("Invoice Date", "2099-04-15", "future"),
        ("Supplier GSTIN", "not-a-gstin", "GSTIN"),
        ("Supplier GSTIN", "27AAPFU0939F1ZV", "selected business"),
        ("Taxable Value", "-1000", "non-negative"),
        ("Taxable Value", "1000.001", "decimal"),
        ("Taxable Value", "", "required"),
        ("IGST", "NaN", "non-negative"),
        ("Total Value", "999", "differs"),
        ("ITC Eligible", "maybe", "yes or no"),
    ],
)
def test_invalid_financial_rows_cannot_be_imported(auth_client, column, value, message):
    rows = list(csv.reader(io.StringIO(register_csv(("CHECK",)).decode())))
    rows[1][rows[0].index(column)] = value
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    result = preview(auth_client, output.getvalue().encode())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["ready"] == 0 and body["invalid"] == 1
    assert message in " ".join(body["rows"][0]["errors"])
    assert (
        auth_client.post(API + f'/register-imports/{body["id"]}/commit', json={}).status_code == 422
    )


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"Invoice Number\n",
        b"A,A\n1,2\n",
        b"A,B\n1\n",
        b"\xff\xfe",
    ],
)
def test_unreadable_registers_return_a_useful_error_without_a_draft(auth_client, content):
    result = auth_client.post(
        API + "/register-imports/preview",
        files={
            "file": ("invalid.csv", content, "text/csv"),
        },
    )
    assert result.status_code == 422
    assert result.json()["detail"]


def test_case_variations_are_skipped_when_the_books_change_after_preview(auth_client):
    first = preview(auth_client, register_csv(("CASE-1",))).json()
    second = preview(auth_client, register_csv(("case-1",))).json()
    assert (
        auth_client.post(API + f'/register-imports/{first["id"]}/commit', json={}).json()[
            "imported"
        ]
        == 1
    )
    result = auth_client.post(API + f'/register-imports/{second["id"]}/commit', json={})
    assert result.status_code == 200, result.text
    assert result.json()["imported"] == 0 and result.json()["duplicates_skipped"] == 1


def test_blank_itc_eligibility_is_never_inferred_from_the_tax_amount(auth_client, db_session):
    content = register_csv(("NO-ITC",)).replace(b",yes", b",")
    draft = preview(auth_client, content).json()
    result = auth_client.post(API + f'/register-imports/{draft["id"]}/commit', json={})
    assert result.status_code == 200, result.text
    invoice = db_session.get(Invoice, result.json()["invoice_ids"][0])
    assert invoice.itc_eligible is False
    assert invoice.extraction_confidence is None
