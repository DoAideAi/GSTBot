"""Supplier handoffs preserve scope, source facts and accountant decisions."""
import csv
import io
from copy import deepcopy

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from app.models.mixins import utcnow
from app.models.practice import FindingReviewEvent, ReportReview
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


@pytest.fixture()
def run(db_session, business):
    findings = []
    for number, gstin, category, books, portal in [
        ("A-001", SUPPLIER_GSTIN_SAME_STATE, "missing_in_2b", "180.10", None),
        ("A-002", SUPPLIER_GSTIN_SAME_STATE, "mismatched", "100.10", "80.05"),
        ("B-001", SUPPLIER_GSTIN_OTHER_STATE, "missing_in_2b", "500.00", None),
        ("MATCHED", SUPPLIER_GSTIN_SAME_STATE, "matched", "90.00", "90.00"),
        ("INTERNAL", SUPPLIER_GSTIN_SAME_STATE, "missing_in_books", None, "180.00"),
        ("UNKNOWN", None, "missing_in_2b", "20.00", None),
    ]:
        findings.append({"invoice_number": number, "supplier_gstin": gstin,
            "supplier_name": "Supplier A" if gstin == SUPPLIER_GSTIN_SAME_STATE else "Supplier B",
            "invoice_date": "2026-04-15", "category": category,
            "books": {"total_tax": books} if books else None,
            "gstr2b": {"total_tax": portal} if portal else None,
            "differences": [{"field": "total_tax", "books": "100.10", "gstr2b": "80.05"}]
            if category == "mismatched" else [], "note": "Recorded matching explanation"})
    row = ReconciliationRun(business_id=business.id, period="2026-04",
        status=ReconciliationStatus.COMPLETED, completed_at=utcnow(), report={"findings": findings})
    db_session.add(row)
    db_session.commit()
    return row


def url(run, suffix):
    return f"/api/v1/practice/runs/{run.id}/{suffix}"


def resolve(client, run, index, note="Checked invoice evidence"):
    response = client.patch(url(run, f"findings/{index}"), json={
        "version": 0, "status": "resolved", "decision": "accept_match", "note": note})
    assert response.status_code == 200, response.text


def approve(client, run):
    for index, finding in enumerate(run.report["findings"]):
        if finding["category"] != "matched":
            resolve(client, run, index, note="=HYPERLINK(\"https://example.com\")")
    response = client.post(url(run, "approve"))
    assert response.status_code == 200, response.text


def test_queue_prioritizes_exact_differences_and_separates_internal_exceptions(auth_client, run):
    response = auth_client.get(url(run, "supplier-followups"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["total"] == 3 and data["unassigned"] == 1
    assert [g["absolute_tax_difference"] for g in data["suppliers"]] == ["500.00", "200.15"]
    assert [i["invoice_number"] for i in data["suppliers"][1]["items"]] == ["A-001", "A-002"]
    assert data["suppliers"][1]["items"][0]["invoice_date"] == "2026-04-15"
    assert "books 100.10; 2B 80.05" in data["suppliers"][1]["items"][1]["differences"]


def test_resolution_removes_findings_and_explicit_followup_includes_other_categories(
    auth_client, run,
):
    resolve(auth_client, run, 0)
    response = auth_client.patch(url(run, "findings/4"), json={
        "version": 0, "status": "in_review", "decision": "follow_up", "note": "Private note"})
    assert response.status_code == 200
    groups = auth_client.get(url(run, "supplier-followups")).json()["suppliers"]
    a = next(g for g in groups if g["gstin"] == SUPPLIER_GSTIN_SAME_STATE)
    assert [i["invoice_number"] for i in a["items"]] == ["A-002", "INTERNAL"]
    assert "Private note" not in str(groups)


def test_draft_and_csv_include_only_selected_supplier_without_recording_contact(
    auth_client, run, db_session,
):
    before = db_session.scalar(select(func.count()).select_from(FindingReviewEvent))
    draft = auth_client.get(url(run, "supplier-draft"), params={"gstin": SUPPLIER_GSTIN_SAME_STATE})
    assert draft.status_code == 200
    assert "A-001" in draft.json()["body"] and "B-001" not in draft.json()["body"]
    assert "does not by itself establish" in draft.json()["body"]
    response = auth_client.get(url(run, "supplier-invoices.csv"),
        params={"gstin": SUPPLIER_GSTIN_SAME_STATE})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 2 and {r["Supplier GSTIN"] for r in rows} == {SUPPLIER_GSTIN_SAME_STATE}
    assert rows[0]["Recorded invoice date"] == "2026-04-15"
    assert db_session.scalar(select(func.count()).select_from(FindingReviewEvent)) == before
    assert db_session.scalar(select(ReportReview)) is None


def test_supplier_csv_neutralizes_formulas(auth_client, run, db_session):
    report = deepcopy(run.report)
    report["findings"][0]["invoice_number"] = " =WEBSERVICE(\"https://example.com\")"
    run.report = report
    db_session.commit()
    response = auth_client.get(url(run, "supplier-invoices.csv"),
        params={"gstin": SUPPLIER_GSTIN_SAME_STATE})
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["Invoice"].startswith("' =")


def test_a_draft_cannot_download_a_different_set_of_findings(auth_client, run):
    data = auth_client.get(url(run, "supplier-draft"),
        params={"gstin": SUPPLIER_GSTIN_SAME_STATE}).json()
    params = {"gstin": SUPPLIER_GSTIN_SAME_STATE, "draft_fingerprint": data["fingerprint"]}
    assert auth_client.get(url(run, "supplier-invoices.csv"), params=params).status_code == 200
    resolve(auth_client, run, 0)
    response = auth_client.get(url(run, "supplier-invoices.csv"), params=params)
    assert response.status_code == 409
    assert "changed after this draft" in response.json()["detail"]


@pytest.mark.parametrize("suffix", ["supplier-draft", "supplier-invoices.csv"])
def test_historical_runs_cannot_generate_current_supplier_handoffs(
    auth_client, run, db_session, suffix,
):
    db_session.add(ReconciliationRun(business_id=run.business_id, period=run.period,
        status=ReconciliationStatus.COMPLETED, completed_at=utcnow(), report={"findings": []}))
    db_session.commit()
    assert auth_client.get(url(run, "supplier-followups")).json()["stale"]
    assert auth_client.get(url(run, suffix),
        params={"gstin": SUPPLIER_GSTIN_SAME_STATE}).status_code == 409


def test_supplier_selection_cannot_export_a_supplier_with_no_open_findings(auth_client, run):
    resolve(auth_client, run, 0)
    resolve(auth_client, run, 1)
    assert auth_client.get(url(run, "supplier-invoices.csv"),
        params={"gstin": SUPPLIER_GSTIN_SAME_STATE}).status_code == 404
    response = auth_client.get(url(run, "supplier-draft"), params={"gstin": "not-a-gstin"})
    assert response.status_code == 422


def test_workbook_preserves_report_entitlement_and_review_gates(auth_client, run, db_session):
    response = auth_client.get(url(run, "export.xlsx"))
    assert response.status_code == 402
    response = auth_client.post("/api/v1/subscriptions/pilot", json={"tier": "enterprise"})
    assert response.status_code == 200
    assert auth_client.get(url(run, "export.xlsx")).status_code == 409
    assert db_session.scalar(select(ReportReview)) is None
    approve(auth_client, run)
    assert auth_client.get(url(run, "export.xlsx")).status_code == 200
    assert db_session.scalar(select(ReportReview)).exported_at is not None


def test_workbook_contains_numeric_totals_literal_notes_and_complete_history(auth_client, run):
    auth_client.post("/api/v1/subscriptions/pilot", json={"tier": "enterprise"})
    approve(auth_client, run)
    response = auth_client.get(url(run, "export.xlsx"))
    assert response.status_code == 200
    assert "spreadsheetml.sheet" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    book = load_workbook(io.BytesIO(response.content), data_only=False)
    assert book.sheetnames == ["Summary", "Suppliers", "Findings", "Review history"]
    assert book["Findings"].max_row == 7
    assert book["Findings"]["H2"].value == pytest.approx(180.10)
    assert book["Findings"]["F2"].value == "2026-04-15"
    assert book["Findings"]["M2"].value.startswith("=HYPERLINK")
    assert book["Findings"]["M2"].data_type == "s"
    assert book["Review history"].max_row == 6
    assert all(c.data_type != "f" for sheet in book for row in sheet for c in row)
    assert book["Findings"].freeze_panes == "A2"
    book.close()


def test_workbook_refuses_changed_sources_and_retains_prior_export_state(
    auth_client, run, db_session,
):
    auth_client.post("/api/v1/subscriptions/pilot", json={"tier": "enterprise"})
    approve(auth_client, run)
    db_session.add(ReconciliationRun(business_id=run.business_id, period=run.period,
        status=ReconciliationStatus.COMPLETED, completed_at=utcnow(), report={"findings": []}))
    db_session.commit()
    assert auth_client.get(url(run, "export.xlsx")).status_code == 409
    assert db_session.scalar(select(ReportReview)).exported_at is None
