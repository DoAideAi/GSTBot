"""Jev (TypeSafe System One): advisory HSN, supply-category, risk and routing answers.

The contract that matters most is what happens when Jev *can't* answer — no
key, an outage, a malformed or off-vocabulary reply all come back as ``None``,
and the invoice pipeline carries on as if Jev didn't exist. The second is that
nothing Jev says is written over a parsed figure or picks the tax heads.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.invoice import Invoice, InvoiceType
from app.services import hsn, jev_service
from tests import jev_mock
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE
from tests.jev_mock import choice, score

ALL_FOUR = {
    "invoice_category": choice("B2B", 0.93, {"B2B": 0.93, "B2C": 0.07}),
    "compliance_risk": score(1.2, 0.7, {"0": 0.2, "1": 0.5, "2": 0.25, "3": 0.05}),
    "tax_routing": choice("inter_state_igst", 0.88),
    "hsn_chapter": choice("73", 0.81),
}


@pytest.fixture(autouse=True)
def _no_cooldown():
    jev_service.reset_cooldown()
    yield
    jev_service.reset_cooldown()


def _invoice(**over) -> Invoice:
    fields = dict(
        id=1,
        invoice_type=InvoiceType.PURCHASE,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Bolt Works",
        invoice_number="INV-7",
        invoice_date=date(2026, 4, 15),
        place_of_supply="27",
        hsn_code=None,
        tax_rate=Decimal("18"),
        taxable_value=Decimal("1000.00"),
        cgst=Decimal("0"), sgst=Decimal("0"), igst=Decimal("180.00"),
        cess=Decimal("0"), total_value=Decimal("1180.00"),
        reverse_charge=False,
        line_items=None,
        raw_text=None,
    )
    fields.update(over)
    return Invoice(**fields)


# ---------------------------------------------------------------------------
# Not configured, failing, malformed
# ---------------------------------------------------------------------------


class TestWithoutAnAnswer:
    def test_without_a_key_no_request_is_made_and_nothing_is_returned(self, monkeypatch):
        mock = jev_mock.install(monkeypatch, api_key="  ")
        assert jev_service.is_configured() is False
        assert jev_service.classify_hsn_chapter("steel bolts") is None
        assert jev_service.assess_invoice(_invoice()) is None
        assert mock.calls == 0

    def test_an_api_error_returns_none_and_pauses_jev(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.status = 500
        assert jev_service.categorize_invoice("x") is None
        assert mock.calls == 1

        # Cooling down: the next call doesn't reach the API at all.
        mock.status = 200
        mock.answers = {"invoice_category": choice("B2C")}
        assert jev_service.categorize_invoice("x") is None
        assert mock.calls == 1

        jev_service.reset_cooldown()
        assert jev_service.categorize_invoice("x").label == "B2C"

    def test_a_transport_failure_never_raises(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.raise_exc = RuntimeError("connection reset")
        assert jev_service.route_transaction("x") is None

    def test_a_label_outside_the_question_is_no_answer(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"invoice_category": choice("wholesale")}
        assert jev_service.categorize_invoice("x") is None

    def test_a_missing_answer_is_no_answer(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {}
        assert jev_service.score_compliance_risk("x") is None
        assert jev_service.route_transaction("x") is None

    def test_an_answer_of_the_wrong_shape_is_no_answer(self):
        class _Broken:
            @property
            def choices(self):
                raise ValueError("bad payload")

            scores = choices

        assert jev_service._choice(_Broken(), "tax_routing", jev_service.TAX_ROUTES) is None
        assert jev_service._risk(_Broken(), "compliance_risk") is None

    def test_an_assessment_with_no_usable_answer_is_none(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"invoice_category": choice("wholesale")}
        assert jev_service.assess_invoice(_invoice()) is None


# ---------------------------------------------------------------------------
# The four questions on their own
# ---------------------------------------------------------------------------


class TestHsnChapters:
    def test_the_chapters_offered_are_exactly_the_ones_the_hsn_table_ships(self):
        chapters = jev_service.hsn_chapters()
        assert set(chapters) == {e.code[:2] for e in hsn.entries()}
        assert "Services" in chapters["99"]
        assert "Machinery" in chapters["84"]

    def test_a_description_is_classified_into_a_chapter(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"hsn_chapter": choice("73", 0.84)}

        result = jev_service.classify_hsn_chapter("galvanised steel hex bolts")

        assert result.label == "73"
        assert result.confidence == pytest.approx(0.84)
        q = mock.questions()["hsn_chapter"]
        assert q["type"] == "choice"
        assert set(q["criteria"]) == set(jev_service.hsn_chapters())
        assert "galvanised steel hex bolts" in mock.state()


class TestInvoiceCategory:
    def test_the_six_supply_categories_are_offered(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"invoice_category": choice("SEZ", 0.77)}

        assert jev_service.categorize_invoice("Supply to SEZ unit").label == "SEZ"
        assert set(mock.questions()["invoice_category"]["criteria"]) == {
            "B2B", "B2C", "export", "SEZ", "nil_rated", "exempt",
        }


class TestComplianceRisk:
    def test_the_rubric_is_sent_lowest_risk_first(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"compliance_risk": score(2.0)}
        jev_service.score_compliance_risk("x")

        rubric = mock.questions()["compliance_risk"]["criteria"]
        assert [r.split(":")[0] for r in rubric] == list(jev_service.RISK_LEVELS)

    @pytest.mark.parametrize(
        ("value", "level"),
        [(0.0, "low_risk"), (0.49, "low_risk"), (1.6, "high_risk"), (3.0, "critical_risk")],
    )
    def test_the_expected_score_names_its_nearest_level(self, monkeypatch, value, level):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"compliance_risk": score(value)}
        assert jev_service.score_compliance_risk("x").level == level

    def test_a_score_outside_the_rubric_is_clamped_to_its_ends(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"compliance_risk": score(7.5, confidence=1.4)}
        risk = jev_service.score_compliance_risk("x")
        assert risk.level == "critical_risk"
        assert risk.score == 3.0
        assert risk.confidence == 1.0

    def test_probabilities_are_keyed_by_level_name(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"compliance_risk": score(
            1.0, probabilities={"0": 0.1, "1": 0.7, "2": 0.1, "3": 0.05, "9": 0.05},
        )}
        risk = jev_service.score_compliance_risk("x")
        # A level the rubric doesn't have is dropped, not mislabelled.
        assert risk.probabilities == {
            "low_risk": 0.1, "moderate_risk": 0.7, "high_risk": 0.1, "critical_risk": 0.05,
        }
        assert risk.as_dict()["level"] == "moderate_risk"


class TestTransactionRouting:
    def test_the_two_routes_are_offered(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"tax_routing": choice("intra_state_cgst_sgst", 0.9)}
        assert jev_service.route_transaction("x").label == "intra_state_cgst_sgst"
        assert set(mock.questions()["tax_routing"]["criteria"]) == {
            "intra_state_cgst_sgst", "inter_state_igst",
        }

    def test_a_purchase_is_routed_by_the_suppliers_state(self):
        assert jev_service.route_by_state_codes(_invoice(), BUSINESS_GSTIN) == "inter_state_igst"
        same = _invoice(counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE)
        assert jev_service.route_by_state_codes(same, BUSINESS_GSTIN) == "intra_state_cgst_sgst"

    def test_a_sale_is_routed_by_our_own_state(self):
        sale = _invoice(invoice_type=InvoiceType.SALES, place_of_supply="29")
        assert jev_service.route_by_state_codes(sale, BUSINESS_GSTIN) == "inter_state_igst"
        assert jev_service.route_by_state_codes(sale, None) is None

    @pytest.mark.parametrize(
        "over",
        [{"place_of_supply": None}, {"counterparty_gstin": None},
         {"counterparty_gstin": "29AAGCB7383J1Z0"}],
        ids=["no place of supply", "no supplier GSTIN", "an invalid GSTIN"],
    )
    def test_without_both_states_the_rule_does_not_decide(self, over):
        assert jev_service.route_by_state_codes(_invoice(**over), BUSINESS_GSTIN) is None


# ---------------------------------------------------------------------------
# A whole invoice
# ---------------------------------------------------------------------------


class TestAssessInvoice:
    def test_all_four_questions_go_in_one_request(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ALL_FOUR

        result = jev_service.assess_invoice(_invoice(), business_gstin=BUSINESS_GSTIN)

        assert mock.calls == 1
        assert set(mock.questions()) == {
            "invoice_category", "compliance_risk", "tax_routing", "hsn_chapter",
        }
        assert result["model"] == "jev-test"
        assert result["invoice_category"]["label"] == "B2B"
        assert result["compliance_risk"]["level"] == "moderate_risk"
        assert result["hsn_chapter"] == {
            "label": "73", "confidence": 0.81, "probabilities": {"73": 0.81},
            "heading": jev_service.hsn_chapters()["73"],
        }

    def test_a_stated_hsn_code_is_not_second_guessed(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ALL_FOUR
        result = jev_service.assess_invoice(_invoice(hsn_code="7318"))
        assert "hsn_chapter" not in mock.questions()
        assert "hsn_chapter" not in result

    def test_jevs_route_is_stored_beside_the_state_code_rule(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"tax_routing": choice("inter_state_igst", 0.88)}
        assessed = jev_service.assess_invoice(_invoice(), business_gstin=BUSINESS_GSTIN)
        routing = assessed["tax_routing"]
        assert routing["label"] == "inter_state_igst"
        assert routing["by_state_codes"] == "inter_state_igst"
        assert routing["disagrees_with_state_codes"] is False

    def test_a_route_that_contradicts_the_state_codes_is_flagged(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"tax_routing": choice("intra_state_cgst_sgst", 0.6)}
        assessed = jev_service.assess_invoice(_invoice(), business_gstin=BUSINESS_GSTIN)
        routing = assessed["tax_routing"]
        assert routing["disagrees_with_state_codes"] is True

    def test_no_disagreement_is_claimed_when_the_rule_cannot_decide(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = {"tax_routing": choice("intra_state_cgst_sgst", 0.6)}
        routing = jev_service.assess_invoice(_invoice(place_of_supply=None))["tax_routing"]
        assert routing["by_state_codes"] is None
        assert routing["disagrees_with_state_codes"] is False

    def test_the_state_carries_the_parsed_fields_line_items_and_text(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ALL_FOUR
        jev_service.assess_invoice(
            _invoice(
                line_items=[{"description": "Hex bolts M8", "hsn_code": None}, "junk"],
                raw_text="TAX INVOICE ... " + "x" * 10000,
                tax_rate=None,
            ),
            business_gstin=BUSINESS_GSTIN,
        )
        state = mock.state()
        assert "recorded as a purchase" in state
        assert SUPPLIER_GSTIN_OTHER_STATE in state
        assert BUSINESS_GSTIN in state
        assert "IGST 180.00" in state
        assert "rate: unknown" in state
        assert "Hex bolts M8 (HSN none)" in state
        assert "TAX INVOICE" in state
        assert "[truncated]" in state

    def test_a_sale_says_so_in_the_state(self, monkeypatch):
        mock = jev_mock.install(monkeypatch)
        mock.answers = ALL_FOUR
        sale = _invoice(invoice_type=InvoiceType.SALES, counterparty_gstin=None)
        jev_service.assess_invoice(sale)
        assert "recorded as a sale" in mock.state()
        assert "rate: 18%" in mock.state()


def test_as_dict_rounds_for_storage():
    c = jev_service.JevChoice("B2B", 0.123456, {"B2B": 0.123456})
    assert c.as_dict() == {"label": "B2B", "confidence": 0.1235, "probabilities": {"B2B": 0.1235}}
