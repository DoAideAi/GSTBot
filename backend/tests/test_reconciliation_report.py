"""The paid PDF report of a reconciliation run: buy, verify, download."""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import settings
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.models.report_purchase import ReportPurchase
from app.services import razorpay_client
from app.services.reconciliation_report import period_label, rupees

SECRET = "test_report_secret"
PRICE = razorpay_client.REPORT_PRICE_PAISE


@pytest.fixture(autouse=True)
def razorpay_keys(monkeypatch):
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_publishable")
    monkeypatch.setattr(settings, "razorpay_key_secret", SECRET)


def _signature(order_id: str, payment_id: str) -> str:
    return hmac.new(
        SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def _run(db_session, business, *, status=ReconciliationStatus.COMPLETED, supplier="Acme Traders"):
    run = ReconciliationRun(
        business_id=business.id,
        period="2026-04",
        status=status,
        total_invoices=2,
        matched_count=1,
        missing_in_2b_count=1,
        itc_eligible=Decimal("1800.00"),
        itc_at_risk=Decimal("1234567.50"),
        itc_claimed=Decimal("1236367.50"),
        completed_at=datetime(2026, 5, 14, tzinfo=UTC),
        report={
            "credit_notes": "0",
            "findings": [
                {
                    "category": "missing_in_2b",
                    "supplier_name": supplier,
                    "supplier_gstin": "29AABCU9603R1ZM",
                    "invoice_number": "INV-0042",
                    "invoice_date": "2026-04-03",
                    "books": {"total_tax": "1234567.50"},
                    "differences": [],
                },
                {
                    "category": "mismatched",
                    "supplier_name": "Gamma Steel",
                    "supplier_gstin": "24AAACG1234A1Z5",
                    "invoice_number": "G-19",
                    "carried": True,
                    "note": "Filed late by the supplier.",
                    "books": {"total_tax": "900.00"},
                    "gstr2b": {"total_tax": "810.00"},
                    "differences": [
                        {"field": "total_tax", "books": "900.00", "gstr2b": "810.00"},
                        "not a difference",
                    ],
                },
                {
                    "category": "matched",
                    "supplier_name": "Beta Supplies",
                    "supplier_gstin": "27AAPFU0939F1ZV",
                    "invoice_number": "B-7",
                    "books": {"total_tax": "1800.00"},
                    "gstr2b": {"total_tax": "1800.00"},
                    "differences": [],
                },
            ],
        },
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def _paid_order(business_id: int, run_id: int, **overrides) -> dict:
    order = {
        "id": "order_rpt",
        "receipt": razorpay_client.report_receipt(business_id, run_id),
        "amount": PRICE,
        "amount_paid": PRICE,
        "currency": "INR",
        "status": "paid",
    }
    return {**order, **overrides}


def _verify(client, run_id, *, order="order_rpt", payment="pay_rpt", signature=None):
    return client.post(
        "/api/v1/reconciliation/report/verify",
        json={
            "run_id": run_id,
            "razorpay_order_id": order,
            "razorpay_payment_id": payment,
            "razorpay_signature": signature or _signature(order, payment),
        },
    )


def _buy(client, business, run, **order_overrides):
    with patch.object(
        razorpay_client, "fetch_order",
        return_value=_paid_order(business.id, run.id, **order_overrides),
    ):
        return _verify(client, run.id)


def _pdf_text(body: bytes) -> str:
    # Whitespace collapsed: a table cell wraps its text across lines, and where
    # the wrap falls is layout, not content.
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(body)).pages)
    return " ".join(text.split())


class TestStartingAPurchase:
    def test_an_order_is_created_for_this_run_at_the_report_price(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        created = {"id": "order_rpt", "amount": PRICE, "currency": "INR"}
        with patch.object(razorpay_client, "create_order", return_value=created) as create:
            r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})

        assert r.status_code == 200
        create.assert_called_once_with(
            amount_paise=PRICE, receipt=razorpay_client.report_receipt(business.id, run.id)
        )
        body = r.json()
        assert body["already_purchased"] is False
        assert body["order_id"] == "order_rpt"
        assert body["amount"] == 9900
        assert body["razorpay_key_id"] == "rzp_test_publishable"

    def test_the_key_secret_never_reaches_the_browser(self, auth_client, db_session, business):
        run = _run(db_session, business)
        created = {"id": "order_rpt", "amount": PRICE, "currency": "INR"}
        with patch.object(razorpay_client, "create_order", return_value=created):
            r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})
        assert SECRET not in r.text

    def test_a_report_already_paid_for_is_not_charged_for_again(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        assert _buy(auth_client, business, run).status_code == 200

        with patch.object(razorpay_client, "create_order") as create:
            r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})

        create.assert_not_called()
        assert r.json() == {
            "run_id": run.id,
            "already_purchased": True,
            "order_id": None,
            "amount": None,
            "currency": None,
            "razorpay_key_id": None,
        }

    def test_another_tenants_run_named_in_the_body_is_not_found(
        self, auth_client, db_session, business, other_tenant
    ):
        run = _run(db_session, business)
        r = auth_client.post(
            "/api/v1/reconciliation/report/purchase",
            json={"run_id": run.id},
            headers={"Authorization": f"Bearer {other_tenant}"},
        )
        assert r.status_code == 404

    def test_a_run_that_failed_has_no_report_to_buy(self, auth_client, db_session, business):
        run = _run(db_session, business, status=ReconciliationStatus.FAILED)
        r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})
        assert r.status_code == 409

    def test_without_razorpay_configured_checkout_is_refused_as_unavailable(
        self, auth_client, db_session, business, monkeypatch
    ):
        monkeypatch.setattr(settings, "razorpay_key_secret", "")
        run = _run(db_session, business)
        r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})
        assert r.status_code == 503

    def test_razorpay_failing_to_create_the_order_is_a_retryable_502(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        with patch.object(razorpay_client, "create_order", return_value=None):
            r = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})
        assert r.status_code == 502


class TestVerifyingThePayment:
    def test_a_verified_payment_records_the_purchase_and_says_where_to_download(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        r = _buy(auth_client, business, run)

        assert r.status_code == 200
        assert r.json() == {
            "run_id": run.id,
            "purchased": True,
            "download_path": f"/reconciliation/{run.id}/report.pdf",
        }
        row = db_session.scalar(select(ReportPurchase).where(ReportPurchase.run_id == run.id))
        assert row.razorpay_payment_id == "pay_rpt"
        assert row.amount_paise == PRICE

    def test_a_forged_signature_records_nothing(self, auth_client, db_session, business):
        run = _run(db_session, business)
        with patch.object(razorpay_client, "fetch_order") as fetch:
            r = _verify(auth_client, run.id, signature="0" * 64)
        assert r.status_code == 400
        fetch.assert_not_called()
        assert db_session.scalar(select(ReportPurchase)) is None

    def test_a_payment_for_another_runs_report_does_not_buy_this_one(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        r = _buy(
            auth_client, business, run,
            receipt=razorpay_client.report_receipt(business.id, run.id + 1),
        )
        assert r.status_code == 400
        assert db_session.scalar(select(ReportPurchase)) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"status": "attempted", "amount_paid": 0},
            {"amount": 100, "amount_paid": 100},
        ],
        ids=["unpaid", "a-cheaper-order"],
    )
    def test_an_order_not_paid_in_full_at_the_report_price_is_refused(
        self, auth_client, db_session, business, overrides
    ):
        run = _run(db_session, business)
        assert _buy(auth_client, business, run, **overrides).status_code == 400

    def test_razorpay_unreachable_is_a_retryable_502(self, auth_client, db_session, business):
        run = _run(db_session, business)
        with patch.object(razorpay_client, "fetch_order", return_value=None):
            assert _verify(auth_client, run.id).status_code == 502

    def test_verifying_the_same_payment_again_succeeds_without_a_second_row(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        assert _buy(auth_client, business, run).status_code == 200
        with patch.object(razorpay_client, "fetch_order") as fetch:
            again = _verify(auth_client, run.id)
        assert again.status_code == 200
        fetch.assert_not_called()
        assert len(db_session.scalars(select(ReportPurchase)).all()) == 1

    def test_one_payment_cannot_buy_a_second_runs_report(self, auth_client, db_session, business):
        first = _run(db_session, business)
        second = _run(db_session, business)
        assert _buy(auth_client, business, first).status_code == 200
        r = _verify(auth_client, second.id)
        assert r.status_code == 409

    def test_a_double_submitted_verify_that_loses_the_race_still_succeeds(
        self, auth_client, db_session, business, monkeypatch
    ):
        """Both requests can pass the "already recorded?" read; the constraint
        keeps one row and the loser answers from it."""
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        run = _run(db_session, business)
        real_commit = Session.commit
        calls = {"n": 0}

        def commit_that_loses_once(self):
            calls["n"] += 1
            if calls["n"] == 1:
                self.rollback()
                self.add(
                    ReportPurchase(
                        business_id=business.id, run_id=run.id, razorpay_order_id="order_rpt",
                        razorpay_payment_id="pay_rpt", amount_paise=PRICE,
                    )
                )
                real_commit(self)
                raise IntegrityError("INSERT INTO report_purchases", {}, Exception("unique"))
            return real_commit(self)

        monkeypatch.setattr(Session, "commit", commit_that_loses_once)
        r = _buy(auth_client, business, run)
        assert r.status_code == 200
        assert r.json()["purchased"] is True


    def test_a_second_payment_against_a_paid_order_is_refused_and_not_recorded(
        self, auth_client, db_session, business
    ):
        """Two payments can land on one order; the first bought the report, so
        the order constraint keeps the second out and it is reported as the
        conflict it is rather than as a second purchase."""
        run = _run(db_session, business)
        assert _buy(auth_client, business, run).status_code == 200
        with patch.object(
            razorpay_client, "fetch_order", return_value=_paid_order(business.id, run.id)
        ):
            r = _verify(auth_client, run.id, payment="pay_second")
        assert r.status_code == 409
        assert len(db_session.scalars(select(ReportPurchase)).all()) == 1


class TestDownloading:
    def test_an_unbought_report_asks_for_payment(self, auth_client, db_session, business):
        run = _run(db_session, business)
        r = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf")
        assert r.status_code == 402

    def test_a_bought_report_is_the_runs_findings_and_itc_impact(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        _buy(auth_client, business, run)

        r = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf")

        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" in r.headers["content-disposition"]
        assert f"2026-04-run{run.id}.pdf" in r.headers["content-disposition"]
        text = _pdf_text(r.content)
        for expected in (
            "GSTR-2B Reconciliation Report",
            business.gstin,
            "April 2026",
            "Missing in GSTR-2B (1)",
            "INV-0042",
            "Acme Traders",
            "Matched (1)",
            "B-7",
            "Mismatched (1)",
            "total tax: books Rs. 900.00, 2B Rs. 810.00",
            "Booked in an earlier period",
            "Filed late by the supplier.",
            "Rs. 12,34,567.50",
            "Rs. 1,800.00",
        ):
            assert expected in text, expected

    def test_it_can_be_downloaded_again_and_is_the_same_file(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business)
        _buy(auth_client, business, run)
        first = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").content
        second = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").content
        assert first == second

    def test_markup_in_a_supplier_name_is_printed_rather_than_parsed(
        self, auth_client, db_session, business
    ):
        run = _run(db_session, business, supplier="A & B <Traders>")
        _buy(auth_client, business, run)
        r = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf")
        assert r.status_code == 200
        assert "A & B <Traders>" in _pdf_text(r.content)


class TestPeriodLabel:
    def test_a_period_is_named_by_month(self):
        assert period_label("2026-04") == "April 2026"

    def test_anything_else_is_printed_as_it_came(self):
        assert period_label("Q1 2026") == "Q1 2026"


class TestRupees:
    @pytest.mark.parametrize(
        ("value", "printed"),
        [
            ("0", "Rs. 0.00"),
            ("999.5", "Rs. 999.50"),
            ("1800", "Rs. 1,800.00"),
            ("123456.789", "Rs. 1,23,456.79"),
            ("1234567.50", "Rs. 12,34,567.50"),
            ("-250000", "-Rs. 2,50,000.00"),
            ("not a number", "Rs. 0.00"),
        ],
    )
    def test_amounts_use_indian_grouping(self, value, printed):
        assert rupees(value) == printed

    @pytest.mark.parametrize(
        ("value", "printed"),
        [("0.005", "Rs. 0.01"), ("0.015", "Rs. 0.02"), ("1234.565", "Rs. 1,234.57")],
    )
    def test_a_half_paisa_rounds_up_like_every_other_figure_in_the_app(self, value, printed):
        """The default context rounds half-even, so 0.005 printed as 0.00 —
        a different paisa from the screen the report was bought from."""
        assert rupees(value) == printed

    @pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "sNaN"])
    def test_a_non_finite_amount_is_unreadable_not_a_crash(self, value):
        """The sign test raised on NaN, which took the whole PDF download down."""
        assert rupees(value) == "Rs. 0.00"


def test_every_match_category_has_a_section_in_the_report():
    """A category without one would be counted in the summary and its rows
    left out of the report the customer paid for."""
    from app.services.reconciliation import MatchCategory
    from app.services.reconciliation_report import SECTIONS

    assert {section[0] for section in SECTIONS} == set(MatchCategory)
