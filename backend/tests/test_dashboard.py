"""The dashboard: counts, the tax summary, and the liability arithmetic."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.routers.dashboard import _net_liability, _previous_periods
from app.schemas.dashboard import TaxBucket
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE


def make_invoice(db, business_id, **kwargs) -> Invoice:
    """Insert an invoice directly, so a test controls the exact figures."""
    defaults = dict(
        business_id=business_id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        invoice_number="T-1",
        invoice_date=date(2026, 4, 10),
        period="2026-04",
        taxable_value=Decimal("0.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("0.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("0.00"),
        extraction_confidence=0.9,
    )
    defaults.update(kwargs)
    invoice = Invoice(**defaults)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def test_dashboard_requires_authentication(client):
    assert client.get("/api/v1/dashboard").status_code == 401


def test_empty_dashboard_is_all_zeroes(auth_client):
    body = auth_client.get("/api/v1/dashboard").json()
    assert body["business_gstin"] == BUSINESS_GSTIN
    assert body["business_name"] == "Umang Traders"
    assert body["counts"]["total"] == 0
    assert Decimal(body["output_tax"]) == Decimal("0.00")
    assert Decimal(body["net_liability"]["total"]) == Decimal("0.00")


def test_a_business_without_a_gstin_has_null_in_the_dashboard(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "nogstin@example.com",
            "password": "supersecret123",
            "legal_name": "Bare Books LLP",
            "full_name": "Bare Books",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    body = client.get(
        "/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert body["business_gstin"] is None
    assert body["business_name"] == "Bare Books LLP"


def test_counts_split_by_type_and_status(auth_client, db_session, business):
    make_invoice(db_session, business.id, invoice_type=InvoiceType.SALES, invoice_number="S-1")
    make_invoice(db_session, business.id, invoice_type=InvoiceType.SALES, invoice_number="S-2")
    make_invoice(db_session, business.id, invoice_type=InvoiceType.PURCHASE, invoice_number="P-1")
    make_invoice(
        db_session,
        business.id,
        invoice_number="P-2",
        status=InvoiceStatus.FAILED,
        extraction_confidence=0.1,
    )

    counts = auth_client.get("/api/v1/dashboard").json()["counts"]
    assert counts["total"] == 4
    assert counts["sales"] == 2
    assert counts["purchase"] == 2
    assert counts["by_status"][InvoiceStatus.PARSED.value] == 3
    assert counts["by_status"][InvoiceStatus.FAILED.value] == 1


def test_low_confidence_invoices_are_queued_for_review(auth_client, db_session, business):
    make_invoice(db_session, business.id, invoice_number="OK-1", extraction_confidence=0.95)
    make_invoice(db_session, business.id, invoice_number="LOW-1", extraction_confidence=0.2)
    make_invoice(db_session, business.id, invoice_number="NONE-1", extraction_confidence=None)

    assert auth_client.get("/api/v1/dashboard").json()["counts"]["needs_review"] == 2


def test_tax_summary_totals_the_period(auth_client, db_session, business):
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.SALES, invoice_number="S-1",
        taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
        total_value=Decimal("118000.00"),
    )
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.PURCHASE, invoice_number="P-1",
        taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
        total_value=Decimal("59000.00"),
    )

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert Decimal(body["sales"]["igst"]) == Decimal("18000.00")
    assert Decimal(body["sales"]["total_tax"]) == Decimal("18000.00")
    assert Decimal(body["purchase"]["total_tax"]) == Decimal("9000.00")
    assert Decimal(body["output_tax"]) == Decimal("18000.00")
    assert Decimal(body["input_tax_credit"]) == Decimal("9000.00")
    assert Decimal(body["net_liability"]["igst"]) == Decimal("9000.00")
    assert Decimal(body["net_liability"]["total"]) == Decimal("9000.00")


def test_liability_is_kept_separate_per_head(auth_client, db_session, business):
    """CGST credit cannot discharge an SGST liability.

    Netting the heads together would show this business owing nothing, when
    in fact it owes the whole SGST and is sitting on unusable CGST credit.
    """
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.SALES, invoice_number="S-1",
        taxable_value=Decimal("100000.00"), sgst=Decimal("9000.00"),
        total_value=Decimal("109000.00"),
    )
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.PURCHASE, invoice_number="P-1",
        taxable_value=Decimal("100000.00"), cgst=Decimal("9000.00"),
        total_value=Decimal("109000.00"),
    )

    liability = auth_client.get("/api/v1/dashboard?period=2026-04").json()["net_liability"]
    assert Decimal(liability["sgst"]) == Decimal("9000.00")
    assert Decimal(liability["cgst"]) == Decimal("0.00")
    assert Decimal(liability["total"]) == Decimal("9000.00")


def test_excess_credit_floors_at_zero_rather_than_going_negative(
    auth_client, db_session, business
):
    """Surplus credit carries forward; it is not money coming back."""
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.SALES, invoice_number="S-1",
        taxable_value=Decimal("10000.00"), igst=Decimal("1800.00"),
        total_value=Decimal("11800.00"),
    )
    make_invoice(
        db_session, business.id,
        invoice_type=InvoiceType.PURCHASE, invoice_number="P-1",
        taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
        total_value=Decimal("118000.00"),
    )

    liability = auth_client.get("/api/v1/dashboard?period=2026-04").json()["net_liability"]
    assert Decimal(liability["igst"]) == Decimal("0.00")
    assert Decimal(liability["total"]) == Decimal("0.00")


def test_the_period_filter_scopes_the_money_but_not_the_counts(
    auth_client, db_session, business
):
    make_invoice(
        db_session, business.id, invoice_number="APR-1", period="2026-04",
        invoice_date=date(2026, 4, 5), igst=Decimal("1000.00"),
    )
    make_invoice(
        db_session, business.id, invoice_number="MAY-1", period="2026-05",
        invoice_date=date(2026, 5, 5), igst=Decimal("2000.00"),
    )

    april = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert Decimal(april["purchase"]["igst"]) == Decimal("1000.00")
    assert april["counts"]["total"] == 2  # Counts are lifetime.

    may = auth_client.get("/api/v1/dashboard?period=2026-05").json()
    assert Decimal(may["purchase"]["igst"]) == Decimal("2000.00")


def test_a_failed_invoice_is_counted_but_its_money_is_not(auth_client, db_session, business):
    """The badge should show the document; the liability should not.

    A failed extraction can still carry figures — a re-parse of an invoice
    that read cleanly the first time leaves them behind. The returns leave the
    row out, so the dashboard's net liability has to leave it out too, or a
    business plans its cash around a number its GSTR-3B will not show.
    """
    make_invoice(
        db_session,
        business.id,
        invoice_type=InvoiceType.SALES,
        invoice_number="S-1",
        status=InvoiceStatus.FAILED,
        taxable_value=Decimal("100000.00"),
        igst=Decimal("18000.00"),
        total_value=Decimal("118000.00"),
    )

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

    assert body["counts"]["total"] == 1
    assert body["counts"]["by_status"]["failed"] == 1
    assert body["sales"]["count"] == 0
    assert Decimal(body["sales"]["igst"]) == Decimal("0.00")
    assert Decimal(body["net_liability"]["total"]) == Decimal("0.00")


def test_soft_deleted_invoices_are_excluded(auth_client, db_session, business):
    invoice = make_invoice(db_session, business.id, invoice_number="D-1",
                           igst=Decimal("5000.00"))
    invoice.soft_delete()
    db_session.commit()

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["counts"]["total"] == 0
    assert Decimal(body["purchase"]["igst"]) == Decimal("0.00")


def test_another_tenants_invoices_never_appear(client, auth_client, other_tenant, db_session):
    from app.models.business import Business

    rival = db_session.query(Business).filter_by(legal_name="Rival Trading Co").one()
    make_invoice(db_session, rival.id, invoice_number="R-1", igst=Decimal("99999.00"))

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["counts"]["total"] == 0
    assert Decimal(body["purchase"]["igst"]) == Decimal("0.00")


def test_plan_usage_is_reported(auth_client, db_session, business, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=50")
    make_invoice(db_session, business.id, invoice_number="U-1")

    usage = auth_client.get("/api/v1/dashboard").json()["plan_usage"]
    assert usage["plan"] == "free"
    assert usage["monthly_limit"] == 50
    assert usage["invoices_this_month"] == 1
    assert usage["remaining"] == 49


def test_an_unlimited_plan_reports_no_remaining(auth_client, db_session, business, monkeypatch):
    from app.core.config import settings
    from app.models.business import BusinessPlan

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=50,pro=0")
    business.plan = BusinessPlan.PRO
    db_session.commit()

    usage = auth_client.get("/api/v1/dashboard").json()["plan_usage"]
    assert usage["monthly_limit"] == 0
    assert usage["remaining"] is None


def test_the_gstr3b_due_date_is_the_twentieth_of_the_next_month(auth_client):
    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["next_due_date"] == "2026-05-20"


def test_the_due_date_rolls_over_the_year(auth_client):
    body = auth_client.get("/api/v1/dashboard?period=2026-12").json()
    assert body["next_due_date"] == "2027-01-20"


def test_the_gstr1_due_date_is_the_eleventh_of_the_next_month(auth_client):
    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["gstr1_due_date"] == "2026-05-11"


def test_the_gstr1_due_date_rolls_over_the_year(auth_client):
    body = auth_client.get("/api/v1/dashboard?period=2026-12").json()
    assert body["gstr1_due_date"] == "2027-01-11"


def test_recent_periods_run_oldest_first_and_cross_the_year(auth_client):
    periods = [p["period"] for p in auth_client.get(
        "/api/v1/dashboard?period=2026-02").json()["recent_periods"]]
    assert periods == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]


def test_previous_periods_helper():
    assert _previous_periods("2026-03", 3) == ["2026-01", "2026-02", "2026-03"]
    assert _previous_periods("2026-01", 2) == ["2025-12", "2026-01"]


def test_itc_at_risk_comes_from_the_latest_reconciliation(auth_client, db_session, business):
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period="2026-04",
            status=ReconciliationStatus.COMPLETED,
            matched_count=8,
            mismatched_count=1,
            missing_in_2b_count=2,
            itc_eligible=Decimal("70000.00"),
            itc_at_risk=Decimal("12000.00"),
        )
    )
    db_session.commit()

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert Decimal(body["itc_at_risk"]) == Decimal("12000.00")
    assert body["last_reconciliation"]["matched"] == 8
    assert body["last_reconciliation"]["missing_in_2b"] == 2


def test_a_later_failed_run_does_not_reset_the_risk_to_nil(
    auth_client, db_session, business
):
    """A failed run's zeros are column defaults, not a reconciled position.

    Reconciling again after a completed run is routine — suppliers file late and
    the portal regenerates the 2B — and the attempt can fail. It is then the
    newest row for the period, and every figure on it is zero, so the dashboard
    reported no ITC at risk at all: the reassuring answer, on the one screen a
    business checks to decide whether to chase a supplier.
    """
    for status, at_risk in (
        (ReconciliationStatus.COMPLETED, Decimal("12000.00")),
        (ReconciliationStatus.FAILED, Decimal("0.00")),
    ):
        db_session.add(
            ReconciliationRun(
                business_id=business.id,
                period="2026-04",
                status=status,
                matched_count=8 if status is ReconciliationStatus.COMPLETED else 0,
                missing_in_2b_count=2 if status is ReconciliationStatus.COMPLETED else 0,
                itc_at_risk=at_risk,
                error=None if status is ReconciliationStatus.COMPLETED else "boom",
            )
        )
        db_session.commit()

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert Decimal(body["itc_at_risk"]) == Decimal("12000.00")
    assert body["last_reconciliation"]["status"] == "completed"
    assert body["last_reconciliation"]["matched"] == 8


def test_a_run_still_in_flight_is_not_read_as_a_result(auth_client, db_session, business):
    """A worker that died mid-run leaves a RUNNING row behind for good."""
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period="2026-04",
            status=ReconciliationStatus.COMPLETED,
            itc_at_risk=Decimal("12000.00"),
        )
    )
    db_session.commit()
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period="2026-04",
            status=ReconciliationStatus.RUNNING,
        )
    )
    db_session.commit()

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert Decimal(body["itc_at_risk"]) == Decimal("12000.00")


def test_a_period_whose_only_run_failed_reads_as_unreconciled(
    auth_client, db_session, business
):
    """No completed run is no reconciliation, not one that found nothing."""
    db_session.add(
        ReconciliationRun(
            business_id=business.id,
            period="2026-04",
            status=ReconciliationStatus.FAILED,
            error="boom",
        )
    )
    db_session.commit()

    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["last_reconciliation"] is None


def test_a_malformed_period_is_rejected(auth_client):
    assert auth_client.get("/api/v1/dashboard?period=2026-4").status_code == 422
    assert auth_client.get("/api/v1/dashboard?period=April").status_code == 422


def test_dashboard_reflects_a_real_upload(auth_client, sample_invoice_text):
    """End to end: the number on the invoice reaches the dashboard."""
    auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("inv.txt", sample_invoice_text.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
    )
    body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
    assert body["counts"]["purchase"] == 1
    assert Decimal(body["purchase"]["igst"]) == Decimal("81000.00")
    assert Decimal(body["input_tax_credit"]) == Decimal("81000.00")


class TestNotEveryPurchaseIsCredit:
    """Tax paid on a purchase and credit claimable from it are two figures.

    Netting output tax against every purchase overstates the credit a business
    holds, and so understates the cash it has to find by the twentieth. The
    dashboard reports both: ``purchase`` is what the invoices say, ``credit``
    is the claimable part, and only the second discharges liability.
    """

    def test_a_blocked_purchase_shows_as_purchase_but_not_as_credit(
        self, auth_client, db_session, business
    ):
        """s.17(5) — a car, a staff lunch, a club membership.

        The tax was genuinely paid and belongs on the purchase side; it is
        simply not claimable, so it cannot pay down the month's liability.
        """
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-BLOCKED",
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"), itc_eligible=False,
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert Decimal(body["purchase"]["igst"]) == Decimal("9000.00")
        assert Decimal(body["credit"]["igst"]) == Decimal("0.00")
        assert Decimal(body["input_tax_credit"]) == Decimal("0.00")
        assert Decimal(body["net_liability"]["igst"]) == Decimal("18000.00")

    def test_a_reverse_charge_purchase_is_not_credit_either(
        self, auth_client, db_session, business
    ):
        """The supplier charged nothing; the buyer self-assesses.

        There is no tax on this document for the buyer to have paid to the
        supplier, so treating it as credit would net a liability against tax
        that never changed hands.
        """
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-RCM",
            taxable_value=Decimal("40000.00"), igst=Decimal("7200.00"),
            total_value=Decimal("47200.00"), reverse_charge=True,
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert Decimal(body["purchase"]["igst"]) == Decimal("7200.00")
        assert Decimal(body["credit"]["igst"]) == Decimal("0.00")
        assert Decimal(body["net_liability"]["igst"]) == Decimal("18000.00")

    def test_a_reverse_charge_sale_is_not_in_the_liability(
        self, auth_client, db_session, business
    ):
        """P16 M2: the recipient pays that tax, so it is not this business's to pay.

        Still shown in the sales totals — it is a document this business
        issued — but not netted into what the landing screen says is owed.
        """
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-RCM",
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"), reverse_charge=True,
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert Decimal(body["sales"]["igst"]) == Decimal("27000.00")
        assert Decimal(body["net_liability"]["igst"]) == Decimal("18000.00")

    def test_the_claimable_purchases_in_a_mixed_period_still_net(
        self, auth_client, db_session, business
    ):
        """One of each: only the clean purchase reduces what is owed."""
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("200000.00"), igst=Decimal("36000.00"),
            total_value=Decimal("236000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-OK",
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-BLOCKED",
            taxable_value=Decimal("30000.00"), igst=Decimal("5400.00"),
            total_value=Decimal("35400.00"), itc_eligible=False,
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-RCM",
            taxable_value=Decimal("20000.00"), igst=Decimal("3600.00"),
            total_value=Decimal("23600.00"), reverse_charge=True,
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert body["purchase"]["count"] == 3
        assert Decimal(body["purchase"]["igst"]) == Decimal("18000.00")
        assert Decimal(body["purchase"]["taxable_value"]) == Decimal("100000.00")
        # Only P-OK survives both tests.
        assert body["credit"]["count"] == 1
        assert Decimal(body["credit"]["igst"]) == Decimal("9000.00")
        assert Decimal(body["credit"]["taxable_value"]) == Decimal("50000.00")
        assert Decimal(body["input_tax_credit"]) == Decimal("9000.00")
        assert Decimal(body["net_liability"]["igst"]) == Decimal("27000.00")

    def test_a_sale_never_contributes_to_the_credit_bucket(
        self, auth_client, db_session, business
    ):
        """Credit comes off the purchase side only.

        A sale carries the same ``itc_eligible`` default as anything else, so
        a claimable-total that scanned every row would fold output tax into
        the credit pool and wipe out the liability it is meant to discharge.
        """
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("100000.00"), cgst=Decimal("9000.00"),
            sgst=Decimal("9000.00"), total_value=Decimal("118000.00"),
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert body["credit"]["count"] == 0
        assert Decimal(body["credit"]["total_tax"]) == Decimal("0.00")
        assert Decimal(body["net_liability"]["total"]) == Decimal("18000.00")

    def test_recent_periods_net_against_credit_too(
        self, auth_client, db_session, business
    ):
        """The trend row is the same arithmetic, and has to agree with it."""
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-MAR",
            period="2026-03", invoice_date=date(2026, 3, 9),
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-MAR",
            period="2026-03", invoice_date=date(2026, 3, 11),
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"), itc_eligible=False,
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
        march = next(p for p in body["recent_periods"] if p["period"] == "2026-03")

        assert Decimal(march["purchase"]["igst"]) == Decimal("9000.00")
        assert Decimal(march["credit"]["igst"]) == Decimal("0.00")
        assert Decimal(march["net_liability"]["igst"]) == Decimal("18000.00")

    def test_a_failed_purchase_is_kept_out_of_credit_as_well(
        self, auth_client, db_session, business
    ):
        """The status filter has to apply to the claimable columns too."""
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-FAILED",
            status=InvoiceStatus.FAILED, extraction_confidence=0.1,
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"),
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()

        assert body["purchase"]["count"] == 0
        assert body["credit"]["count"] == 0
        assert Decimal(body["credit"]["igst"]) == Decimal("0.00")


class TestTheChartCostsOneScanRatherThanSeven:
    """The dashboard's seven period summaries came from seven scans.

    ``tax_summary`` is documented as one grouped query "because the dashboard
    is the most-hit endpoint in the product and a business can hold tens of
    thousands of invoices" — and the dashboard then called it once for the
    selected period and once per month of history, six of the seven differing
    only in which month they filtered to.
    """

    def test_one_aggregate_covers_every_period_on_the_screen(
        self, auth_client, db_session, business
    ):
        from sqlalchemy import event

        make_invoice(db_session, business.id, invoice_number="A-1")
        statements: list[str] = []
        engine = db_session.get_bind()

        def _record(conn, cursor, statement, parameters, context, executemany):
            squashed = " ".join(statement.split()).lower()
            if "from invoices" in squashed and "sum(" in squashed:
                statements.append(squashed)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            assert auth_client.get("/api/v1/dashboard?period=2026-04").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        # Two scans: the fused lifetime counts (type×status) and the
        # fused tax summaries (period×direction). Both are single-pass
        # grouped queries rather than one per dimension or one per month.
        assert len(statements) == 2, f"{len(statements)} scans:\n" + "\n".join(statements)
        assert all("group by" in s for s in statements)

    def test_the_history_still_reads_month_by_month(
        self, auth_client, db_session, business
    ):
        """One query must not mean one bucket: the months stay separate."""
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-FEB",
            period="2026-02", invoice_date=date(2026, 2, 5),
            taxable_value=Decimal("10000.00"), igst=Decimal("1800.00"),
            total_value=Decimal("11800.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-MAR",
            period="2026-03", invoice_date=date(2026, 3, 5),
            taxable_value=Decimal("20000.00"), igst=Decimal("3600.00"),
            total_value=Decimal("23600.00"),
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
        by_period = {row["period"]: row for row in body["recent_periods"]}

        assert Decimal(by_period["2026-02"]["sales"]["igst"]) == Decimal("1800.00")
        assert Decimal(by_period["2026-03"]["sales"]["igst"]) == Decimal("3600.00")
        assert Decimal(by_period["2026-04"]["sales"]["igst"]) == Decimal("0.00")

    def test_a_month_with_no_invoices_is_a_zero_row_not_a_missing_one(
        self, auth_client, db_session, business
    ):
        """The chart keeps its gaps: six months in, six months out."""
        make_invoice(db_session, business.id, invoice_number="A-1")

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
        rows = body["recent_periods"]

        assert [row["period"] for row in rows] == _previous_periods("2026-04", 6)
        empty = next(row for row in rows if row["period"] == "2025-12")
        assert empty["sales"]["count"] == 0
        assert Decimal(empty["net_liability"]["total"]) == Decimal("0.00")

    def test_the_selected_period_agrees_with_its_own_row_in_the_history(
        self, auth_client, db_session, business
    ):
        """Both now come out of one result, and must not disagree."""
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-APR",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )

        body = auth_client.get("/api/v1/dashboard?period=2026-04").json()
        april = next(row for row in body["recent_periods"] if row["period"] == "2026-04")

        assert april["sales"] == body["sales"]
        assert april["net_liability"] == body["net_liability"]


class TestTaxSummariesAgreesWithTaxSummary:
    """The batched form has to be the same arithmetic, period by period."""

    def test_each_period_matches_the_single_period_call(self, db_session, business):
        from app.services import invoice_service

        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-1",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.PURCHASE, invoice_number="P-1",
            period="2026-03", invoice_date=date(2026, 3, 9),
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"), reverse_charge=True,
        )

        periods = ["2026-03", "2026-04", "2026-05"]
        batched = invoice_service.tax_summaries(db_session, business.id, periods)

        for period in periods:
            assert batched[period] == invoice_service.tax_summary(
                db_session, business.id, period
            ), period

    def test_a_repeated_period_is_asked_for_once_and_answered_once(
        self, db_session, business
    ):
        from app.services import invoice_service

        make_invoice(db_session, business.id, invoice_number="A-1")
        batched = invoice_service.tax_summaries(
            db_session, business.id, ["2026-04", "2026-04", "2026-03"]
        )
        assert sorted(batched) == ["2026-03", "2026-04"]

    def test_no_periods_asks_the_database_nothing(self, db_session, business):
        from app.services import invoice_service

        assert invoice_service.tax_summaries(db_session, business.id, []) == {}

    def test_no_period_at_all_totals_every_period_rather_than_none_of_them(
        self, db_session, business
    ):
        """``period=None`` is "the whole book", not "the period called None".

        The two arms of ``tax_summary`` reach ``_summarise`` differently — one
        passes ``periods=[period]``, the other passes no filter — so "all
        periods" is a separate query shape rather than the same one with a
        wider list, and nothing else in the product exercises it: every caller
        today (``filing``, ``late_fee``, the dashboard) names a period.

        It is the lifetime figure a business is shown when it has not picked a
        month, so getting it wrong understates the book rather than erroring.
        Pinned against the sum of the periods it covers, which is the only
        definition of right that does not restate the implementation.
        """
        from app.services import invoice_service

        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-APR",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
            total_value=Decimal("118000.00"),
        )
        make_invoice(
            db_session, business.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-MAR",
            period="2026-03", invoice_date=date(2026, 3, 9),
            taxable_value=Decimal("50000.00"), igst=Decimal("9000.00"),
            total_value=Decimal("59000.00"),
        )

        everything = invoice_service.tax_summary(db_session, business.id)
        march = invoice_service.tax_summary(db_session, business.id, "2026-03")
        april = invoice_service.tax_summary(db_session, business.id, "2026-04")

        assert everything["sales"]["count"] == 2
        assert (
            everything["sales"]["total_tax"]
            == march["sales"]["total_tax"] + april["sales"]["total_tax"]
            == Decimal("27000.00")
        )
        # Not the same answer as any single period — the assertion above would
        # also hold if one month were silently being returned as the total.
        assert everything["sales"]["count"] > april["sales"]["count"]

    def test_no_period_at_all_still_scopes_to_one_tenant(
        self, db_session, business, other_tenant
    ):
        # The unfiltered arm drops the period predicate. Dropping the tenant
        # one alongside it would be invisible on a single-tenant test box and
        # would put a competitor's turnover on the dashboard.
        from app.models.business import Business
        from app.services import invoice_service

        rival = db_session.query(Business).filter(Business.id != business.id).one()
        make_invoice(
            db_session, rival.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-OTHER",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
        )

        assert invoice_service.tax_summary(db_session, business.id)["sales"]["count"] == 0

    def test_another_tenants_invoices_are_not_in_any_period(
        self, db_session, business, other_tenant
    ):
        """The batched form still scopes to one tenant, as the single one does."""
        from app.models.business import Business
        from app.services import invoice_service

        rival = db_session.query(Business).filter(Business.id != business.id).one()
        make_invoice(
            db_session, rival.id,
            invoice_type=InvoiceType.SALES, invoice_number="S-OTHER",
            taxable_value=Decimal("100000.00"), igst=Decimal("18000.00"),
        )
        batched = invoice_service.tax_summaries(db_session, business.id, ["2026-04"])

        assert batched["2026-04"]["sales"]["count"] == 0


def test_the_net_liability_card_sets_credit_off_across_heads():
    """IGST credit settles CGST and SGST; head-by-head netting said ₹2,000 to pay."""
    sales = TaxBucket(cgst=Decimal("1000"), sgst=Decimal("1000"))
    credit = TaxBucket(igst=Decimal("2000"))

    net = _net_liability(sales, credit)

    assert net.total == Decimal("0.00")
    assert (net.cgst, net.sgst, net.igst) == (Decimal("0.00"),) * 3


def test_the_net_liability_card_never_lets_cgst_credit_pay_sgst():
    net = _net_liability(TaxBucket(sgst=Decimal("1000")), TaxBucket(cgst=Decimal("1000")))

    assert net.sgst == Decimal("1000.00")
    assert net.total == Decimal("1000.00")
