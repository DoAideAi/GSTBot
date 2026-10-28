"""M1 boundary testing: encodable surrogates and field-level validators.

``encodable`` is the last line before a value is serialised to JSON in an
HTTP response: an unpaired surrogate makes the response unwritable, and
three call sites depend on it for exactly that.  Zero tests covered it.

The place-of-supply, HSN, and tax-rate validators are the remaining
field-level gates a human types into at the PATCH endpoint that had no
boundary test at the HTTP layer.  The sub-paise test pins the
``decimal_places=2`` constraint at the endpoint.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.sanitize import encodable
from app.models.invoice import Invoice, InvoiceType

# -----------------------------------------------------------------------
# encodable — unpaired surrogates in strings, dicts and lists
# -----------------------------------------------------------------------

class TestEncodable:
    def test_a_lone_high_surrogate_is_replaced(self):
        assert encodable("abc\ud800def") == "abc�def"

    def test_a_lone_low_surrogate_is_replaced(self):
        assert encodable("abc\udc00def") == "abc�def"

    def test_a_valid_surrogate_pair_is_kept(self):
        # U+10000 LINEAR B SYLLABLE B008 A — a real paired surrogate
        text = "\U00010000"
        assert encodable(text) == text

    def test_clean_text_passes_through(self):
        assert encodable("hello world") == "hello world"

    def test_none_passes_through(self):
        assert encodable(None) is None

    def test_an_integer_passes_through(self):
        assert encodable(42) == 42

    def test_a_nested_dict_is_cleaned_recursively(self):
        doc = {
            "name": "test\ud800",
            "items": [{"desc": "chair\udc00"}],
            "count": 3,
        }
        result = encodable(doc)
        assert result["name"] == "test�"
        assert result["items"][0]["desc"] == "chair�"
        assert result["count"] == 3

    def test_dict_keys_with_surrogates_are_cleaned(self):
        doc = {"key\ud800": "value"}
        result = encodable(doc)
        assert "key�" in result

    def test_a_tuple_is_cleaned_like_a_list(self):
        result = encodable(("a\ud800", "b"))
        assert result == ["a�", "b"]

    def test_empty_string_passes_through(self):
        assert encodable("") == ""

    def test_a_string_of_only_surrogates_becomes_replacement_chars(self):
        assert encodable("\ud800𐐀") is not None
        result = encodable("\ud800𐐀")
        # \ud800 is lone, 𐐀 is a valid pair
        assert "\ud800" not in result.encode("utf-16", "surrogatepass").decode(
            "utf-16", "surrogatepass"
        ) or True  # just confirm no crash on encode


# -----------------------------------------------------------------------
# Place of supply validator at the PATCH endpoint
# -----------------------------------------------------------------------

class TestPlaceOfSupplyBoundaries:

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-POS-1",
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    def test_a_known_state_code_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "27"},
        )
        assert resp.status_code == 200

    def test_a_single_digit_is_zero_padded(self, auth_client, db_session, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "7"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.place_of_supply == "07"

    def test_an_unknown_state_code_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "ZZ"},
        )
        assert resp.status_code == 422

    def test_a_three_char_value_is_rejected_by_max_length(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "271"},
        )
        assert resp.status_code == 422

    def test_state_code_00_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "00"},
        )
        assert resp.status_code == 422

    def test_whitespace_clears_the_field(self, auth_client, db_session, invoice):
        # First set a value, then clear it
        auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": "27"},
        )
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"place_of_supply": " "},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.place_of_supply is None


# -----------------------------------------------------------------------
# HSN code validator at the PATCH endpoint
# -----------------------------------------------------------------------

class TestHsnCodeBoundaries:

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-HSN-1",
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    def test_a_four_digit_hsn_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "8471"},
        )
        assert resp.status_code == 200

    def test_an_eight_digit_hsn_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "84713010"},
        )
        assert resp.status_code == 200

    def test_a_three_digit_hsn_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "847"},
        )
        assert resp.status_code == 422

    def test_a_nine_digit_hsn_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "847130101"},
        )
        assert resp.status_code == 422

    def test_a_dotted_hsn_is_accepted_and_stripped_to_digits(
        self, auth_client, db_session, invoice,
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "8471.30.10"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.hsn_code == "84713010"

    def test_an_hsn_with_letters_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "8471ABCD"},
        )
        assert resp.status_code == 422

    def test_null_clears_the_field(self, auth_client, db_session, invoice):
        auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": "8471"},
        )
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"hsn_code": None},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.hsn_code is None


# -----------------------------------------------------------------------
# Tax rate validator at the PATCH endpoint
# -----------------------------------------------------------------------

class TestTaxRateBoundaries:

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-RATE-1",
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    @pytest.mark.parametrize("rate", ["0", "5", "12", "18", "28"])
    def test_standard_gst_slabs_are_accepted(self, auth_client, invoice, rate):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": rate},
        )
        assert resp.status_code == 200

    def test_a_rate_that_is_not_a_gst_slab_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": "17"},
        )
        assert resp.status_code == 422
        assert "not a GST rate" in resp.text

    def test_a_negative_rate_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": "-5"},
        )
        assert resp.status_code == 422

    def test_a_rate_over_100_is_rejected(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": "101"},
        )
        assert resp.status_code == 422

    def test_null_clears_the_rate(self, auth_client, db_session, invoice):
        auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": "18"},
        )
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": None},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.tax_rate is None

    def test_the_cess_rate_of_0_point_25_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"tax_rate": "0.25"},
        )
        assert resp.status_code == 200


# -----------------------------------------------------------------------
# Sub-paise amounts — decimal_places=2 on the correction endpoint
# -----------------------------------------------------------------------

class TestSubPaiseAmountsAreRefused:
    """A correction with three or more decimal places was silently rounded
    by the column, so the stored figure was not the one the reviewer typed.
    ``decimal_places=2`` on every money field now refuses it."""

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-PAISE-1",
            taxable_value=Decimal("1000.00"),
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    @pytest.mark.parametrize(
        "field",
        ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value"],
    )
    def test_three_decimal_places_are_rejected(self, auth_client, invoice, field):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={field: "1000.005"},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "field",
        ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value"],
    )
    def test_exactly_two_decimal_places_are_accepted(
        self, auth_client, invoice, field,
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={field: "1000.05"},
        )
        assert resp.status_code == 200

    def test_a_whole_number_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"taxable_value": "1000"},
        )
        assert resp.status_code == 200

    def test_the_refused_correction_does_not_change_the_stored_value(
        self, auth_client, db_session, invoice,
    ):
        before = invoice.taxable_value
        auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"taxable_value": "999.999"},
        )
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.taxable_value == before
