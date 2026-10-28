"""The GPT Actions API — the free tools as ChatGPT calls them.

Covers each endpoint over HTTP, the services behind them where an edge is
easier to state directly, the OpenAI-only CORS grant, and the published spec
against the routes that actually exist: a spec naming an operation the app does
not serve is a GPT that fails mid-conversation, and nothing else would notice.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.core.routes import collect_api_routes
from app.main import app
from app.services import filing_dates, hsn
from app.services import gst_calculator as calc
from app.services import gstin as gstin_service
from tests.conftest import BUSINESS_GSTIN

GPT = "/api/v1/gpt"
SPEC_FILE = Path(__file__).resolve().parents[1] / "app" / "gpt" / "openapi.yaml"
HSN_JS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "hsnData.js"

# 27 = Maharashtra, 29 = Karnataka. Check digits computed, not copied, so the
# fixtures cannot be a typo away from testing the invalid path by accident.
MH_FIRM = "27AAPFU0939F1ZV"
KA_COMPANY = "29AABCU9603R1Z" + gstin_service.compute_check_digit("29AABCU9603R1Z")
MH_COMPANY = "27AABCU9603R1Z" + gstin_service.compute_check_digit("27AABCU9603R1Z")


def _invoice(client, **overrides):
    body = {
        "seller": {"name": "Seller Traders", "gstin": MH_FIRM},
        "buyer": {"name": "Buyer Pvt Ltd", "gstin": MH_COMPANY},
        "items": [
            {"description": "Steel bolts", "hsn_code": "7318", "quantity": 3,
             "unit_price": "99.99", "gst_rate": 18},
        ],
    }
    body.update(overrides)
    return client.post(f"{GPT}/invoice", json=body)


# ---------------------------------------------------------------------------
# GSTIN
# ---------------------------------------------------------------------------


class TestValidateGstin:
    def test_a_valid_gstin_is_decoded_into_state_pan_and_entity_type(self, client):
        body = client.get(f"{GPT}/gstin/{MH_FIRM}").json()
        assert body["valid"] is True
        assert body["state"] == {"code": "27", "name": "Maharashtra"}
        assert body["pan"] == "AAPFU0939F"
        assert body["entity_type"] == "Firm / LLP"
        assert body["registration_number_in_state"] == "1"

    def test_a_company_pan_is_reported_as_a_company(self, client):
        assert client.get(f"{GPT}/gstin/{KA_COMPANY}").json()["entity_type"] == "Company"

    def test_a_wrong_check_digit_is_a_200_saying_why_not_an_error_status(self, client):
        wrong = MH_FIRM[:-1] + ("A" if MH_FIRM[-1] != "A" else "B")
        response = client.get(f"{GPT}/gstin/{wrong}")
        assert response.status_code == 200
        assert response.json()["valid"] is False
        assert "check digit" in response.json()["error"]

    def test_a_gstin_pasted_with_spaces_and_lowercase_still_validates(self, client):
        body = client.get(f"{GPT}/gstin/27 aapfu0939f 1zv").json()
        assert body["valid"] is True
        assert body["gstin"] == MH_FIRM

    def test_input_longer_than_any_gstin_is_refused_rather_than_echoed(self, client):
        assert client.get(f"{GPT}/gstin/{'A' * 65}").status_code == 422

    def test_an_unassigned_pan_type_letter_has_no_entity_type(self):
        assert gstin_service.entity_type("AAAXA1234A") is None


# ---------------------------------------------------------------------------
# HSN
# ---------------------------------------------------------------------------


class TestSearchHsn:
    def test_a_numeric_query_is_a_code_prefix(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "04"}).json()
        assert body["count"] > 0
        assert all(r["hsn_code"].startswith("04") for r in body["results"])

    def test_every_word_of_a_text_query_must_match(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "fresh fish"}).json()
        assert body["count"] > 0
        for row in body["results"]:
            text = f"{row['description']} {row['category']}".lower()
            assert "fresh" in text and "fish" in text

    def test_a_product_alias_leads_even_when_the_tariff_wording_differs(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "cold drinks"}).json()
        assert body["best_match"]["hsn_code"] == "2202"
        assert body["best_match"]["gst_rate"] == "40"
        assert body["results"][0]["hsn_code"] == "2202"

    def test_a_service_is_labelled_as_a_sac_code(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "9954"}).json()
        assert body["results"][0]["code_type"] == "SAC"
        goods = client.get(f"{GPT}/hsn", params={"q": "1006"}).json()
        assert goods["results"][0]["code_type"] == "HSN"

    def test_rates_are_decimal_strings_not_floats(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "0101"}).json()
        assert body["results"][0]["gst_rate"] == "0"

    def test_nothing_matching_is_an_empty_list_not_an_error(self, client):
        body = client.get(f"{GPT}/hsn", params={"q": "zzzqqqxx"}).json()
        assert body == {**body, "best_match": None, "results": [], "count": 0}

    def test_a_text_search_stops_at_the_limit(self, client):
        assert client.get(f"{GPT}/hsn", params={"q": "fresh", "limit": 2}).json()["count"] == 2

    def test_the_limit_is_honoured(self, client):
        assert client.get(f"{GPT}/hsn", params={"q": "0", "limit": 3}).json()["count"] == 3

    @pytest.mark.parametrize("params", [{"q": ""}, {"q": "x" * 101}, {"q": "rice", "limit": 51}])
    def test_an_unbounded_query_is_refused(self, client, params):
        assert client.get(f"{GPT}/hsn", params=params).status_code == 422

    def test_a_blank_query_finds_nothing(self):
        assert hsn.search("   ") == []
        assert hsn.find_product("  ") is None

    def test_the_backend_table_is_the_one_the_hsn_page_ships(self):
        """``hsn_data.json`` is generated from the page's table, never edited.

        Parsed with a regex rather than by running node, so the suite does not
        grow a JavaScript runtime dependency for one assertion.
        """
        source = HSN_JS.read_text(encoding="utf-8")
        row = re.compile(
            r'\{ code: "(\d+)", desc: "((?:[^"\\]|\\.)*)", rate: ([\d.]+), '
            r'category: "([^"]*)"(, sac: true)? \}'
        )
        js = [
            (c, d.replace('\\"', '"'), Decimal(r), cat, bool(sac))
            for c, d, r, cat, sac in row.findall(source)
        ]
        py = [(e.code, e.description, e.rate, e.category, e.sac) for e in hsn.entries()]
        assert len(js) > 600
        assert js == py

        alias = re.compile(r'\{ product: "([^"]*)", hsn: "(\d+)", rate: ([\d.]+) \}')
        js_aliases = [(p, h, Decimal(r)) for p, h, r in alias.findall(source)]
        assert js_aliases == [(a.product, a.hsn, a.rate) for a in hsn.aliases()]


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class TestCalculateGst:
    def test_exclusive_intra_state_splits_cgst_and_sgst_equally(self, client):
        body = client.get(f"{GPT}/calculate", params={"amount": "1000", "rate": "18"}).json()
        assert (body["cgst"], body["sgst"], body["igst"]) == ("90.00", "90.00", "0.00")
        assert body["total"] == "1180.00"

    def test_the_heads_stay_equal_when_the_total_would_round_to_an_odd_paisa(self, client):
        # 18% of 100.05 is 18.009: halving a rounded 18.01 would give 9.01 and
        # 9.00, which the portal refuses. Each head is 9% of 100.05 = 9.0045.
        body = client.get(f"{GPT}/calculate", params={"amount": "100.05", "rate": "18"}).json()
        assert body["cgst"] == body["sgst"] == "9.00"

    @pytest.mark.parametrize("amount", ["1180", "999.99", "0.01", "12345.67"])
    @pytest.mark.parametrize("supply", ["intra_state", "inter_state"])
    def test_an_inclusive_price_is_reproduced_to_the_paisa(self, client, amount, supply):
        body = client.get(f"{GPT}/calculate", params={
            "amount": amount, "rate": "18", "mode": "inclusive", "supply_type": supply,
        }).json()
        assert Decimal(body["total"]) == Decimal(amount)
        assert Decimal(body["taxable_value"]) + Decimal(body["total_tax"]) == Decimal(amount)

    def test_inter_state_is_all_igst(self, client):
        body = client.get(f"{GPT}/calculate", params={
            "amount": "1000", "rate": "5", "supply_type": "inter_state",
        }).json()
        assert (body["cgst"], body["sgst"], body["igst"]) == ("0.00", "0.00", "50.00")

    def test_two_state_codes_decide_the_split_over_the_stated_supply_type(self, client):
        same = client.get(f"{GPT}/calculate", params={
            "amount": "100", "rate": "18", "supply_type": "inter_state",
            "supplier_state_code": "27", "buyer_state_code": "27",
        }).json()
        assert same["supply_type"] == "intra_state"
        different = client.get(f"{GPT}/calculate", params={
            "amount": "100", "rate": "18", "supplier_state_code": "27", "buyer_state_code": "29",
        }).json()
        assert different["supply_type"] == "inter_state"

    def test_a_rate_that_is_not_a_gst_slab_is_refused_by_name(self, client):
        response = client.get(f"{GPT}/calculate", params={"amount": "100", "rate": "1.8"})
        assert response.status_code == 422
        assert "1.8% is not a GST rate" in response.json()["detail"]

    def test_the_pre_reform_slabs_are_still_accepted_for_old_invoices(self, client):
        for rate in ("12", "28"):
            response = client.get(f"{GPT}/calculate", params={"amount": "100", "rate": rate})
            assert response.status_code == 200

    def test_an_unknown_state_code_is_refused(self, client):
        response = client.get(f"{GPT}/calculate", params={
            "amount": "100", "rate": "18", "supplier_state_code": "98",
        })
        assert response.status_code == 422

    @pytest.mark.parametrize("amount", ["nan", "inf", "-1", "1E+999999999"])
    def test_an_amount_no_money_column_could_hold_is_refused(self, client, amount):
        response = client.get(f"{GPT}/calculate", params={"amount": amount, "rate": "18"})
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "params",
        [{"amount": "1", "rate": "-0"},
         {"amount": "-0", "rate": "18", "mode": "inclusive", "supply_type": "inter_state"}],
    )
    def test_a_negative_zero_is_never_printed_with_its_sign(self, client, params):
        body = client.get(f"{GPT}/calculate", params=params).json()
        assert not [k for k, v in body.items() if isinstance(v, str) and v.startswith("-")]


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


class TestGenerateInvoice:
    def test_two_parties_in_one_state_get_cgst_and_sgst(self, client):
        body = _invoice(client).json()
        assert body["supply_type"] == "intra_state"
        line = body["items"][0]
        assert (line["gross_amount"], line["taxable_value"]) == ("299.97", "299.97")
        # 9% of 299.97 = 26.9973 per head.
        assert (line["cgst"], line["sgst"], line["igst"]) == ("27.00", "27.00", "0.00")
        assert body["totals"]["grand_total"] == "354.00"
        assert body["totals"]["round_off"] == "0.03"

    def test_a_buyer_in_another_state_gets_igst(self, client):
        body = _invoice(client, buyer={"name": "KA Co", "gstin": KA_COMPANY}).json()
        assert body["supply_type"] == "inter_state"
        assert body["totals"]["igst"] == "53.99"
        assert body["totals"]["cgst"] == "0.00"

    def test_place_of_supply_outranks_the_buyers_registered_state(self, client):
        body = _invoice(client, place_of_supply="29").json()
        assert body["supply_type"] == "inter_state"
        assert body["place_of_supply"] == {"code": "29", "name": "Karnataka"}

    def test_a_discount_comes_off_before_tax(self, client):
        body = _invoice(client, items=[{
            "description": "Service", "hsn_code": "9983", "quantity": 1,
            "unit_price": "1000", "gst_rate": 18, "discount_percent": 10,
        }]).json()
        line = body["items"][0]
        assert (line["discount"], line["taxable_value"], line["total_tax"]) == (
            "100.00", "900.00", "162.00",
        )

    def test_the_rate_summary_agrees_with_the_lines_to_the_paisa(self, client):
        items = [
            {"description": "A", "hsn_code": "7318", "quantity": 1,
             "unit_price": "10.01", "gst_rate": 18},
            {"description": "B", "hsn_code": "7318", "quantity": 1,
             "unit_price": "10.01", "gst_rate": 18},
            {"description": "C", "hsn_code": "1006", "quantity": 2,
             "unit_price": "50", "gst_rate": 5},
        ]
        body = _invoice(client, items=items).json()
        summary = {row["gst_rate"]: row for row in body["tax_summary"]}
        assert set(summary) == {"5", "18"}
        lines_18 = [line for line in body["items"] if line["gst_rate"] == "18"]
        assert Decimal(summary["18"]["cgst"]) == sum(Decimal(line["cgst"]) for line in lines_18)
        summed = sum(Decimal(r["total_tax"]) for r in body["tax_summary"])
        assert summed == Decimal(body["totals"]["total_tax"])

    def test_round_off_can_be_turned_off(self, client):
        totals = _invoice(client, round_off=False).json()["totals"]
        assert (totals["grand_total"], totals["round_off"]) == ("353.97", "0.00")

    def test_the_amount_is_written_out_in_words(self, client):
        assert _invoice(client).json()["amount_in_words"] == "Rupees Three Hundred Fifty Four Only"

    def test_the_date_defaults_to_today_in_india(self, client, monkeypatch):
        from app.services import gst_calendar
        monkeypatch.setattr(gst_calendar, "today_ist", lambda: date(2026, 10, 20))
        assert _invoice(client).json()["invoice_date"] == "2026-10-20"
        assert _invoice(client, invoice_date="2026-04-01").json()["invoice_date"] == "2026-04-01"

    def test_a_buyer_without_a_gstin_is_warned_about_as_b2c(self, client):
        body = _invoice(client, buyer={"name": "Walk-in", "state_code": "27"}).json()
        assert body["supply_type"] == "intra_state"
        assert any("B2C" in w for w in body["warnings"])

    @pytest.mark.parametrize(
        "override",
        [
            {"seller": {"name": "   ", "gstin": MH_FIRM}},
            {"buyer": {"name": "\t", "state_code": "27"}},
            {"items": [{"description": "  ", "quantity": 1, "unit_price": "10", "gst_rate": 18}]},
        ],
    )
    def test_a_name_or_description_of_only_spaces_is_refused(self, client, override):
        assert _invoice(client, **override).status_code == 422

    def test_names_come_back_trimmed(self, client):
        body = _invoice(client, seller={"name": "  Seller Traders  ", "gstin": MH_FIRM}).json()
        assert body["seller"]["name"] == "Seller Traders"

    def test_an_empty_buyer_gstin_is_warned_about_as_b2c_too(self, client):
        body = _invoice(client, buyer={"name": "Walk-in", "gstin": "", "state_code": "27"}).json()
        assert body["buyer"]["gstin"] is None
        assert any("B2C" in w for w in body["warnings"])

    @pytest.mark.parametrize("day", ["0001-01-01", "2017-06-30", "2100-01-01", "9999-12-31"])
    def test_an_invoice_date_outside_gst_is_refused(self, client, day):
        response = _invoice(client, invoice_date=day)
        assert response.status_code == 422
        assert "outside GST" in response.json()["detail"]

    def test_gst_s_first_and_last_days_are_accepted(self, client):
        assert _invoice(client, invoice_date="2017-07-01").status_code == 200
        assert _invoice(client, invoice_date="2099-12-31").status_code == 200

    def test_a_negative_zero_line_prints_no_signed_zero(self, client):
        items = [{"description": "Free sample", "quantity": 1, "unit_price": "-0",
                  "gst_rate": "-0", "discount_percent": "-0"}]
        body = _invoice(client, items=items).json()
        printed = [*body["items"][0].values(), *body["tax_summary"][0].values()]
        assert not [v for v in printed if isinstance(v, str) and v.startswith("-0")]

    def test_a_line_without_an_hsn_code_is_named_in_a_warning(self, client):
        items = [{"description": "Thing", "quantity": 1, "unit_price": "10", "gst_rate": 18}]
        warnings = _invoice(client, items=items).json()["warnings"]
        assert any(w.startswith("Line 1 has no HSN") for w in warnings)
        two = _invoice(client, items=items * 2).json()["warnings"]
        assert any(w.startswith("Lines 1, 2 have no HSN") for w in two)

    def test_a_complete_b2b_invoice_has_no_warnings(self, client):
        assert _invoice(client).json()["warnings"] == []

    @pytest.mark.parametrize(
        "overrides, reason",
        [
            ({"seller": {"name": "S", "gstin": MH_FIRM[:-1] + "0"}}, "Seller GSTIN is invalid"),
            ({"seller": {"name": "S", "gstin": MH_FIRM, "state_code": "29"}},
             "registered in state 27"),
            ({"seller": {"name": "S"}}, "Seller needs a GSTIN or a state code"),
            ({"buyer": {"name": "B"}}, "buyer's GSTIN or state code"),
            ({"buyer": {"name": "B", "state_code": "98"}}, "not a GST state code"),
            ({"items": [{"description": "X", "quantity": 1, "unit_price": "1", "gst_rate": 17}]},
             "17% is not a GST rate"),
        ],
    )
    def test_an_invoice_that_cannot_be_taxed_says_why(self, client, overrides, reason):
        response = _invoice(client, **overrides)
        assert response.status_code == 422
        assert reason in response.json()["detail"]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"items": []},
            {"items": [{"description": "X", "quantity": 1, "unit_price": "1",
                        "gst_rate": 18}] * 101},
            {"items": [{"description": "X", "quantity": 0, "unit_price": "1", "gst_rate": 18}]},
            {"items": [{"description": "X", "quantity": 1, "unit_price": "-1", "gst_rate": 18}]},
            {"items": [{"description": "X", "quantity": 1, "unit_price": "1", "gst_rate": 18,
                        "hsn_code": "12"}]},
            {"seller": {"name": "x" * 201, "gstin": MH_FIRM}},
        ],
    )
    def test_a_malformed_invoice_is_refused_at_the_schema(self, client, overrides):
        assert _invoice(client, **overrides).status_code == 422

    def test_the_seller_gstin_used_in_the_suite_fixtures_is_accepted(self, client):
        assert _invoice(client, seller={"name": "S", "gstin": BUSINESS_GSTIN}).status_code == 200


class TestAmountInWords:
    @pytest.mark.parametrize(
        "amount, words",
        [
            ("0", "Rupees Zero Only"),
            ("11", "Rupees Eleven Only"),
            ("300", "Rupees Three Hundred Only"),
            ("100000", "Rupees One Lakh Only"),
            ("1234567.50", "Rupees Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven"
                           " and Fifty Paise Only"),
            ("10000000", "Rupees One Crore Only"),
            ("10000000000", "Rupees One Thousand Crore Only"),
            ("0.05", "Rupees Zero and Five Paise Only"),
        ],
    )
    def test_indian_grouping(self, amount, words):
        assert calc.amount_in_words(Decimal(amount)) == words


# ---------------------------------------------------------------------------
# Filing dates
# ---------------------------------------------------------------------------


def _dates(client, **params):
    response = client.get(f"{GPT}/filing-dates", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {d["form"]: d for d in body["deadlines"]}


class TestFilingDates:
    def test_a_monthly_filer_owes_gstr1_gstr3b_and_the_annual_return(self, client):
        body, by_form = _dates(client, period="2026-09", as_of="2026-10-01")
        assert by_form["GSTR-1"]["due_date"] == "2026-10-11"
        assert by_form["GSTR-3B"]["due_date"] == "2026-10-20"
        assert by_form["GSTR-9"]["due_date"] == "2027-12-31"
        assert body["financial_year"] == "FY 2026-27"

    def test_december_rolls_into_the_next_year(self, client):
        _, by_form = _dates(client, period="2026-12", as_of="2026-12-31")
        assert by_form["GSTR-3B"]["due_date"] == "2027-01-20"

    def test_march_belongs_to_the_financial_year_it_closes(self, client):
        body, by_form = _dates(client, period="2027-03", as_of="2027-04-01")
        assert body["financial_year"] == "FY 2026-27"
        assert by_form["GSTR-9"]["due_date"] == "2027-12-31"

    def test_status_counts_days_from_the_as_of_date(self, client):
        _, upcoming = _dates(client, period="2026-09", as_of="2026-10-15")
        assert upcoming["GSTR-3B"]["days_remaining"] == 5
        assert upcoming["GSTR-3B"]["status"] == "upcoming"
        assert "late_fee_so_far" not in upcoming["GSTR-3B"]
        _, today = _dates(client, period="2026-09", as_of="2026-10-20")
        assert today["GSTR-3B"]["status"] == "due_today"

    def test_an_overdue_return_carries_the_late_fee_so_far(self, client):
        _, by_form = _dates(client, period="2026-09", as_of="2026-10-30")
        assert by_form["GSTR-3B"]["status"] == "overdue"
        assert by_form["GSTR-3B"]["days_remaining"] == -10
        assert by_form["GSTR-3B"]["late_fee_so_far"] == "500.00"
        assert by_form["GSTR-3B"]["nil_return_late_fee_so_far"] == "200.00"

    def test_turnover_sets_the_late_fee_cap(self, client):
        params = {"period": "2026-01", "as_of": "2026-10-30"}
        _, uncapped = _dates(client, **params)
        assert uncapped["GSTR-3B"]["late_fee_so_far"] == "10000.00"
        _, small = _dates(client, **params, previous_year_turnover="1000000")
        assert small["GSTR-3B"]["late_fee_so_far"] == "2000.00"
        assert small["GSTR-3B"]["nil_return_late_fee_so_far"] == "500.00"

    def test_the_annual_return_is_never_given_a_monthly_late_fee(self, client):
        _, by_form = _dates(client, period="2017-07", as_of="2026-10-30")
        assert by_form["GSTR-9"]["status"] == "overdue"
        assert "late_fee_so_far" not in by_form["GSTR-9"]

    def test_a_quarterly_filer_mid_quarter_owes_iff_and_pmt06(self, client):
        _, by_form = _dates(client, period="2026-08", filer_type="quarterly", as_of="2026-09-01")
        assert by_form["IFF"]["due_date"] == "2026-09-13"
        assert by_form["IFF"]["optional"] is True
        assert by_form["PMT-06"]["due_date"] == "2026-09-25"
        assert "GSTR-1" not in by_form

    @pytest.mark.parametrize("state, day", [("27", "22"), ("09", "24")])
    def test_a_quarterly_gstr3b_date_depends_on_the_state_category(self, client, state, day):
        _, by_form = _dates(client, period="2026-09", filer_type="quarterly",
                            state_code=state, as_of="2026-10-01")
        assert by_form["GSTR-1"]["due_date"] == "2026-10-13"
        assert by_form["GSTR-3B"]["due_date"] == f"2026-10-{day}"

    def test_without_a_state_both_quarterly_categories_are_listed(self, client):
        _, by_form = _dates(client, period="2026-09", filer_type="quarterly", as_of="2026-10-01")
        assert by_form["GSTR-3B — Category A states"]["due_date"] == "2026-10-22"
        assert by_form["GSTR-3B — Category B states"]["due_date"] == "2026-10-24"

    def test_a_composition_dealer_owes_cmp08_for_the_quarter_and_gstr4(self, client):
        _, by_form = _dates(client, period="2026-08", filer_type="composition", as_of="2026-09-01")
        assert set(by_form) == {"CMP-08", "GSTR-4"}
        assert by_form["CMP-08"]["due_date"] == "2026-10-18"
        assert by_form["CMP-08"]["covers"] == "quarter ending 2026-09"
        assert by_form["GSTR-4"]["due_date"] == "2027-04-30"

    def test_the_period_defaults_to_last_month(self, client):
        body, _ = _dates(client, as_of="2026-01-05")
        assert body["period"] == "2025-12"

    def test_a_date_before_gst_existed_is_answered_for_its_first_month(self, client):
        body, _ = _dates(client, as_of="2017-07-10")
        assert body["period"] == "2017-07"

    def test_a_date_past_the_last_period_is_refused_not_answered_for_2017(self, client):
        assert _dates(client, as_of="2100-01-31")[0]["period"] == "2099-12"
        for as_of in ("2100-02-01", "9999-12-31"):
            response = client.get(f"{GPT}/filing-dates", params={"as_of": as_of})
            assert response.status_code == 422

    @pytest.mark.parametrize(
        "params",
        [{"period": "2026-13"}, {"period": "2017-06"}, {"state_code": "98"},
         {"filer_type": "annual"}, {"previous_year_turnover": "-1"}],
    )
    def test_a_question_about_something_that_does_not_exist_is_refused(self, client, params):
        assert client.get(f"{GPT}/filing-dates", params=params).status_code == 422

    def test_every_deadline_has_a_known_status(self):
        for filer in filing_dates.FilerType:
            for d in filing_dates.deadlines("2026-06", filer, None):
                status = filing_dates.status_of(d, date(2026, 7, 15)).status
                assert status in {"upcoming", "due_today", "overdue"}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCorsForOpenAI:
    def _preflight(self, client, origin, path=f"{GPT}/hsn"):
        return client.options(path, headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
        })

    @pytest.mark.parametrize(
        "origin", ["https://chatgpt.com", "https://chat.openai.com", "https://platform.openai.com"]
    )
    def test_a_preflight_from_openai_is_granted(self, client, origin):
        response = self._preflight(client, origin)
        assert response.status_code == 204
        assert response.headers["access-control-allow-origin"] == origin
        assert "POST" in response.headers["access-control-allow-methods"]

    def test_a_preflight_from_anywhere_else_is_not(self, client):
        response = self._preflight(client, "https://evil.example")
        assert response.headers.get("access-control-allow-origin") != "https://evil.example"

    def test_openai_gets_no_grant_outside_the_gpt_prefix(self, client):
        response = self._preflight(client, "https://chatgpt.com", path="/api/v1/invoices")
        assert response.headers.get("access-control-allow-origin") != "https://chatgpt.com"

    def test_a_simple_request_from_openai_is_decorated_without_credentials(self, client):
        # The app-wide policy says ``Allow-Credentials: true`` on any response
        # to an Origin; paired with this grant it would be a credentialed one.
        response = client.get(f"{GPT}/hsn", params={"q": "rice"}, headers={"Origin": "https://chatgpt.com"})
        assert response.headers["access-control-allow-origin"] == "https://chatgpt.com"
        assert "access-control-allow-credentials" not in response.headers
        assert "Origin" in response.headers["vary"]

    def test_a_server_side_call_with_no_origin_gets_no_cors_headers(self, client):
        response = client.get(f"{GPT}/hsn", params={"q": "rice"})
        assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------------------
# Spec, privacy and limits
# ---------------------------------------------------------------------------


def _gpt_operations():
    """(path, method) -> route for every GPT route the app actually serves."""
    found = {}
    for route in collect_api_routes(app):
        if not route.path.startswith(GPT):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found[(route.path[len(GPT):], method.lower())] = route
    return found


class TestTheSpecMatchesTheApp:
    @pytest.fixture(scope="class")
    def spec(self):
        return yaml.safe_load(SPEC_FILE.read_text(encoding="utf-8"))

    def test_the_server_is_the_production_gpt_prefix(self, spec):
        assert spec["servers"] == [{"url": f"https://gst.doaide.com{GPT}"}]
        assert spec["openapi"].startswith("3.1")

    def test_every_operation_in_the_spec_is_served_under_the_same_operation_id(self, spec):
        served = _gpt_operations()
        for path, methods in spec["paths"].items():
            for method, operation in methods.items():
                route = served.get((path, method))
                assert route is not None, f"spec names unserved {method.upper()} {path}"
                assert route.operation_id == operation["operationId"]

    def test_every_tool_the_app_serves_is_in_the_spec(self, spec):
        published = {(p, m) for p, methods in spec["paths"].items() for m in methods}
        tools = {k for k, r in _gpt_operations().items() if r.operation_id}
        assert tools == published

    def test_descriptions_fit_openais_limits(self, spec):
        # The GPT builder rejects an operation description over 300 characters.
        for methods in spec["paths"].values():
            for operation in methods.values():
                assert len(operation["description"]) <= 300, operation["operationId"]

    def test_every_schema_reference_resolves(self, spec):
        text = SPEC_FILE.read_text(encoding="utf-8")
        for name in re.findall(r"#/components/schemas/(\w+)", text):
            assert name in spec["components"]["schemas"], name

    def test_the_spec_is_served_for_import_by_url(self, client):
        response = client.get(f"{GPT}/openapi.yaml")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/yaml")
        assert yaml.safe_load(response.text)["info"]["title"] == "DoAide GST Tools"

    def test_the_privacy_policy_is_an_html_page(self, client):
        response = client.get(f"{GPT}/privacy")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "not stored" in response.text


class TestGptRateLimit:
    def test_every_gpt_route_shares_one_retunable_bucket(self, client, rate_limited, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "rate_limit_overrides", "gpt_actions=2/minute")
        assert client.get(f"{GPT}/gstin/{MH_FIRM}").status_code == 200
        assert client.get(f"{GPT}/hsn", params={"q": "rice"}).status_code == 200
        response = client.get(f"{GPT}/calculate", params={"amount": "1", "rate": "18"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers


def test_the_hsn_json_round_trips_through_the_exporter_shape():
    """Guards the file's shape for whoever regenerates it from the page."""
    raw = json.loads((Path(hsn.__file__).with_name("hsn_data.json")).read_text(encoding="utf-8"))
    assert set(raw) == {"hsn", "products"}
    assert set(raw["hsn"][0]) == {"code", "description", "rate", "category", "sac"}
    assert set(raw["products"][0]) == {"product", "hsn", "rate"}

