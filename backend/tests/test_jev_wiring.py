"""Where Jev is consulted: invoice extraction and the GPT HSN search.

Both are advisory. An upload parses to the same figures with Jev on, off or
down; the HSN search only asks Jev when the table had nothing to offer.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services import jev_service
from tests import jev_mock
from tests.jev_mock import choice, score
from tests.test_invoices import upload

GPT = "/api/v1/gpt"

ANSWERS = {
    "invoice_category": choice("B2B", 0.95),
    "compliance_risk": score(0.4, 0.8),
    # The sample is a Karnataka supplier charging IGST. Jev saying intra-state
    # is the case that shows its answer is recorded, never applied.
    "tax_routing": choice("intra_state_cgst_sgst", 0.55),
    "hsn_chapter": choice("84", 0.7),
}


@pytest.fixture(autouse=True)
def _no_cooldown():
    jev_service.reset_cooldown()
    yield
    jev_service.reset_cooldown()


class TestInvoiceExtraction:
    def test_a_parsed_upload_carries_jevs_assessment(
        self, monkeypatch, auth_client, db_session, sample_invoice_text
    ):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ANSWERS

        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]

        assert invoice["status"] == InvoiceStatus.PARSED.value
        jev = invoice["extraction"]["jev"]
        assert jev["invoice_category"]["label"] == "B2B"
        assert jev["compliance_risk"]["level"] == "low_risk"
        # The heuristic parse finds no place of supply in the sample, so the
        # state-code rule can't decide and no disagreement is claimed.
        assert invoice["place_of_supply"] is None
        assert jev["tax_routing"]["label"] == "intra_state_cgst_sgst"
        assert jev["tax_routing"]["by_state_codes"] is None
        assert jev["tax_routing"]["disagrees_with_state_codes"] is False
        assert "INV-2026-0042" in mock.state()
        # Stored, not just returned.
        assert db_session.get(Invoice, invoice["id"]).extraction["jev"] == jev

    def test_jev_never_changes_a_parsed_figure(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ANSWERS
        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]

        # Jev called it intra-state; the invoice charged IGST and keeps it.
        assert Decimal(invoice["igst"]) == Decimal("81000.00")
        assert Decimal(invoice["cgst"]) == Decimal("0")
        assert Decimal(invoice["sgst"]) == Decimal("0")

    def test_without_a_key_the_extraction_is_untouched(self, auth_client, sample_invoice_text):
        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]
        assert invoice["status"] == InvoiceStatus.PARSED.value
        assert "jev" not in invoice["extraction"]

    def test_a_jev_outage_does_not_fail_the_upload(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        mock = jev_mock.install(monkeypatch)
        mock.status = 503
        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]
        assert invoice["status"] == InvoiceStatus.PARSED.value
        assert "jev" not in invoice["extraction"]
        assert mock.calls == 1


class TestHsnSearch:
    def test_a_query_the_table_cannot_match_gets_a_suggested_chapter(self, monkeypatch, client):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"hsn_chapter": choice("84", 0.66)}

        body = client.get(f"{GPT}/hsn", params={"q": "zzzqqqxx"}).json()

        assert body["count"] == 0
        assert body["suggested_chapter"] == {
            "chapter": "84",
            "heading": jev_service.hsn_chapters()["84"],
            "confidence": 0.66,
            "browse_query": "84",
        }
        assert "zzzqqqxx" in mock.state()

    def test_a_table_hit_is_not_second_guessed(self, monkeypatch, client):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"hsn_chapter": choice("84", 0.99)}

        body = client.get(f"{GPT}/hsn", params={"q": "fresh fish"}).json()

        assert body["count"] > 0
        assert "suggested_chapter" not in body
        assert mock.calls == 0

    def test_a_product_alias_hit_is_not_second_guessed(self, monkeypatch, client):
        mock = jev_mock.install(monkeypatch)
        body = client.get(f"{GPT}/hsn", params={"q": "cold drinks"}).json()
        assert body["best_match"]["hsn_code"] == "2202"
        assert mock.calls == 0

    def test_a_miss_without_an_answer_has_no_suggestion(self, monkeypatch, client):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {}
        body = client.get(f"{GPT}/hsn", params={"q": "zzzqqqxx"}).json()
        assert "suggested_chapter" not in body
        assert mock.calls == 1
