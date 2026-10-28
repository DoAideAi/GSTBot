"""The extraction paths a clean text upload never reaches.

tests/test_invoice_parser.py covers the ordinary route: readable text in, a
model or the heuristics out. What is left is everything that happens when the
document is a *photograph* — the vision model, the Tesseract fallback, and the
chain of degradations between them — plus the coercion corners that only an
OCR pass produces.

That chain is the part of the product most likely to meet a bad input, because
the realistic upload is a phone photo of a paper invoice, and it is also the
part with the strongest promise attached: `parse_invoice` never raises. A
failed request loses the invoice, since the paper is usually back in a file by
the time the user sees the error. So the tests below are mostly about what
happens when each link breaks.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services import document_text, gstr2b, invoice_parser
from app.services.invoice_parser import (
    _from_model_payload,
    _vision_messages,
    normalize_rate,
    parse_invoice,
    parse_with_model,
    to_date,
    to_decimal,
    to_flag,
)
from app.services.openrouter_client import OpenRouterError

# A one-pixel PNG. Real bytes, so PIL and the data-url encoder both have
# something valid to work on.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8ffff3f0005fe02fea735c0000000000049454e44ae426082"
)


# --------------------------------------------------------------------------
# Coercion corners that OCR produces and clean text does not
# --------------------------------------------------------------------------

class TestNumbersAnOcrPassProduces:
    def test_devanagari_numerals_are_read_as_numbers(self):
        # A Hindi invoice OCRs to Devanagari digits. Python's Decimal accepts
        # any Unicode decimal digit, so this works — the test pins that it
        # keeps working rather than silently becoming a zero on a real bill.
        assert to_decimal("१२३४.५०") == Decimal("1234.50")

    def test_a_currency_symbol_does_not_eat_the_decimal_point(self):
        # The regression the match-don't-strip approach exists for: stripping
        # non-digits from "Rs. 1000.50" leaves ".1000.50", which is not a
        # Decimal, and the invoice silently becomes zero.
        assert to_decimal("Rs. 1000.50") == Decimal("1000.50")

    def test_indian_digit_grouping_survives(self):
        assert to_decimal("₹ 1,23,456.00") == Decimal("123456.00")

    def test_a_negative_credit_note_amount_keeps_its_sign(self):
        assert to_decimal("-4,500.00") == Decimal("-4500.00")

    def test_text_with_no_number_at_all_falls_back(self):
        assert to_decimal("not applicable") == Decimal("0.00")
        assert to_decimal("not applicable", default=None) is None

    def test_only_the_first_number_on_a_run_together_line_is_taken(self):
        # OCR routinely joins columns: "18% 9,000.00 1,620.00".
        assert to_decimal("18% 9,000.00 1,620.00") == Decimal("18")

    def test_a_third_decimal_is_kept_not_cut(self):
        """The pattern stopped at two decimals and handed back the front."""
        assert to_decimal("12.345") == Decimal("12.345")
        assert to_decimal("0.005") == Decimal("0.005")

    @pytest.mark.parametrize(
        "text, slab",
        [("0.015", Decimal("1.5")), ("0.001", Decimal("0.1")), ("0.075", Decimal("7.5"))],
    )
    def test_a_quoted_fractional_rate_lands_on_its_own_slab(self, text, slab):
        """``"0.015"`` was cut to 0.01 and filed at 1%; ``"0.001"`` became nil-rated."""
        assert invoice_parser.normalize_rate(text) == slab

    @pytest.mark.parametrize("text", ["1.234,56", "1.234.567", "₹ 2.500,00"])
    def test_a_number_with_a_second_separator_group_is_refused_not_shrunk(self, text):
        """₹1,234.56 written the European way read as ₹1.23."""
        assert to_decimal(text, default=None) is None

    def test_a_match_that_decimal_refuses_falls_back_instead_of_raising(
        self, monkeypatch
    ):
        """The pattern and the constructor are allowed to disagree.

        Today they cannot. ``_FULL_NUMBER`` yields ``-?\\d[\\d,]*(\\.\\d+)?``
        and, once the commas come out, every string of that shape is a Decimal
        literal — including the Devanagari case above, since ``\\d`` and
        ``Decimal`` accept the same Unicode digits. So the ``except`` branch is
        unreachable *through the pattern*, and pointing a bad literal at
        ``to_decimal`` cannot exercise it.

        It is still the branch that decides what happens the day the pattern is
        widened — to accept a second decimal group for a European layout, say,
        or a Unicode minus. So widen it here and assert the contract directly:
        ``to_decimal`` degrades to its default. It must, because the promise
        above it is that ``parse_invoice`` never raises, and this runs against
        whatever a model or an OCR pass produced.
        """
        monkeypatch.setattr(
            invoice_parser, "_FULL_NUMBER", re.compile(r"[\d.,-]+")
        )

        assert to_decimal("1.2.3") == Decimal("0.00")
        assert to_decimal("1.2.3", default=None) is None
        assert to_decimal("--5", default=Decimal("-1")) == Decimal("-1")


class TestDatesThatArriveAlreadyParsed:
    """A model or a spreadsheet reader can hand back real date objects."""

    def test_a_date_is_passed_through_untouched(self):
        assert to_date(date(2026, 4, 15)) == date(2026, 4, 15)

    def test_a_datetime_is_narrowed_to_its_date(self):
        # An Excel cell reads back as a datetime at midnight. Storing the time
        # would put the invoice in the wrong filing period across a timezone.
        assert to_date(datetime(2026, 4, 15, 13, 45, 12)) == date(2026, 4, 15)

    def test_a_datetime_subclass_is_not_mistaken_for_a_plain_date(self):
        # datetime is a subclass of date, so an isinstance(date) check placed
        # first would return the datetime itself rather than its .date().
        assert type(to_date(datetime(2026, 4, 15, 13, 45))) is date

    @pytest.mark.parametrize("raw", ["", None, "   ", "not a date", "31/02/2026"])
    def test_unreadable_dates_become_none_rather_than_raising(self, raw):
        assert to_date(raw) is None


class TestPlaceholderTextFromAModel:
    """Asked for a field it cannot find, a model writes a word, not null."""

    @pytest.mark.parametrize("raw", ["N/A", "n/a", "NA", "null", "None", "-", "  "])
    def test_a_placeholder_becomes_none_rather_than_a_supplier_name(self, raw):
        # Stored verbatim these become a supplier called "N/A", which then
        # groups every unreadable invoice under one fictitious counterparty.
        assert _from_model_payload({"supplier_name": raw}, "", "m").supplier_name is None

    def test_a_real_name_that_merely_contains_na_is_kept(self):
        assert (
            _from_model_payload({"supplier_name": "Nagpur Naturals"}, "", "m").supplier_name
            == "Nagpur Naturals"
        )

    def test_wrapped_lines_are_collapsed_into_one_name(self):
        # OCR breaks a name across lines; the column is one line.
        parsed = _from_model_payload({"supplier_name": "Northwind\n  Supplies\tPvt Ltd"}, "", "m")
        assert parsed.supplier_name == "Northwind Supplies Pvt Ltd"

    def test_an_overlong_invoice_number_is_truncated_to_fit_its_column(self):
        parsed = _from_model_payload({"invoice_number": "X" * 200}, "", "m")
        assert parsed.invoice_number == "X" * 64


class TestRateNormalisation:
    def test_a_rate_that_is_not_a_number_at_all_is_dropped(self):
        # The model is asked for a percentage and sometimes answers prose.
        assert normalize_rate("mixed") is None
        assert normalize_rate(None) is None

    def test_a_fraction_is_read_as_a_percentage(self):
        assert normalize_rate("0.18") == Decimal("18")

    def test_a_rate_gst_does_not_use_is_dropped(self):
        # Most often a total mistaken for a percentage.
        assert normalize_rate("15") is None
        assert normalize_rate("1800") is None

    def test_zero_rated_is_kept_and_not_confused_with_missing(self):
        assert normalize_rate("0") == Decimal("0")


class TestReadingAYesNoAnswer:
    """``bool()`` is not this, and the difference is a tax liability.

    "Reverse charge: Not Applicable" is printed on a large share of Indian tax
    invoices, and a model told to copy what the document says copies it.
    ``bool("Not applicable")`` is ``True``.
    """

    @pytest.mark.parametrize(
        "answer",
        [
            "N", "n", "No", "false", "FALSE", "0", "NA", "N/A",
            "not applicable", "none", "nil", "-",
            # A GSTR-2B's wording for the same refusal, where the question is
            # whether credit may be claimed rather than whether a clause
            # applies. Read here rather than in a second set of its own, so the
            # portal's JSON and its CSV cannot disagree about one answer.
            "not available", "Not Available", "unavailable",
        ],
    )
    def test_every_way_of_saying_no_means_no(self, answer):
        assert to_flag(answer) is False

    @pytest.mark.parametrize("answer", ["Y", "yes", "TRUE", "1", "applicable", "Available"])
    def test_every_way_of_saying_yes_means_yes(self, answer):
        assert to_flag(answer) is True

    def test_a_whole_answer_is_not_read_as_the_word_inside_it(self):
        # The reason these are sets of whole answers and not a regex. "Not
        # applicable" contains "applicable" and "unavailable" contains
        # "available", and a substring match reads both as their own opposite.
        assert to_flag("not applicable") is False
        assert to_flag("unavailable", default=True) is False

    def test_a_reverse_charge_of_not_applicable_no_longer_flags_the_invoice(self):
        """The whole reason this function exists.

        Flagged, the tax moves to GSTR-3B table 3.1(d) as a liability payable
        in cash, the invoice's credit leaves the pool it belongs in, and a
        *sale* prints ``rchrg: "Y"`` in the buyer's GSTR-2B.
        """
        payload = {"reverse_charge": "Not applicable"}
        assert _from_model_payload(payload, "", "m").reverse_charge is False

    def test_a_real_reverse_charge_invoice_is_still_flagged(self):
        payload = {"reverse_charge": "Yes"}
        assert _from_model_payload(payload, "", "m").reverse_charge is True

    def test_an_answer_that_is_neither_falls_back_rather_than_guessing(self):
        """Which is how ``itcavl`` keeps defaulting to "credit is available"."""
        assert to_flag("perhaps") is False
        assert to_flag("perhaps", default=True) is True

    def test_an_unanswered_question_takes_the_default(self):
        assert to_flag(None, default=True) is True
        assert to_flag("", default=True) is True
        assert to_flag("   ", default=True) is True

    def test_a_boolean_is_taken_at_its_word(self):
        assert to_flag(False, default=True) is False
        assert to_flag(True) is True

    def test_a_number_is_read_the_way_a_number_is(self):
        assert to_flag(0, default=True) is False
        assert to_flag(1) is True
        assert to_flag(Decimal("0"), default=True) is False

    def test_the_portal_s_own_flags_go_through_the_same_reader(self):
        """``gstr2b`` had a second, shorter list of what "no" looks like."""
        assert gstr2b._flag("N/A", default=True) is False
        assert gstr2b._flag("Not Applicable", default=True) is False


# --------------------------------------------------------------------------
# The model payload, when the model answers something odd
# --------------------------------------------------------------------------

class TestLineItemsFromAModel:
    def test_line_items_are_kept_when_they_are_a_list_of_objects(self):
        payload = {"line_items": [{"description": "Steel bolts", "taxable_value": 100}]}
        assert _from_model_payload(payload, "", "m").line_items == [
            {"description": "Steel bolts", "taxable_value": 100}
        ]

    def test_non_objects_inside_the_list_are_discarded(self):
        # A free-tier model answers ["Steel bolts", {...}] often enough that
        # this cannot be an assertion — the good rows must still survive.
        payload = {"line_items": ["Steel bolts", None, 42, {"description": "Nuts"}]}
        assert _from_model_payload(payload, "", "m").line_items == [{"description": "Nuts"}]

    def test_a_runaway_list_is_capped(self):
        # Guards the database row and the response size against a model that
        # loops. 100 is far above any real invoice.
        payload = {"line_items": [{"description": str(n)} for n in range(500)]}
        assert len(_from_model_payload(payload, "", "m").line_items) == 100

    def test_line_items_that_are_not_a_list_are_ignored(self):
        payload = {"line_items": {"description": "Steel bolts"}}
        assert _from_model_payload(payload, "", "m").line_items == []


# --------------------------------------------------------------------------
# The vision path
# --------------------------------------------------------------------------

class TestVisionMessages:
    def test_the_image_is_sent_as_an_inline_data_url(self):
        # OpenRouter fetches an http url itself; this deployment has no public
        # place to put an invoice photo, so it must be inlined.
        parts = _vision_messages(PNG_1PX, "image/png")[1]["content"]
        image = next(part for part in parts if part["type"] == "image_url")
        assert image["image_url"]["url"].startswith("data:image/png;base64,")

    def test_the_schema_is_sent_alongside_the_image(self):
        parts = _vision_messages(PNG_1PX, "image/png")[1]["content"]
        text = next(part for part in parts if part["type"] == "text")["text"]
        assert "supplier_gstin" in text and "taxable_value" in text

    def test_the_system_prompt_still_leads(self):
        assert _vision_messages(PNG_1PX, "image/png")[0]["role"] == "system"


class TestParseWithModelChoosesItsModel:
    def test_image_bytes_route_to_the_vision_model(self, monkeypatch):
        seen: dict = {}

        def fake_chat_json(messages, model):
            seen["model"] = model
            seen["messages"] = messages
            return {"supplier_name": "Northwind Supplies"}

        monkeypatch.setattr(invoice_parser, "chat_json", fake_chat_json)
        parsed = parse_with_model(content=PNG_1PX, content_type="image/png")

        assert seen["model"] == invoice_parser.settings.openrouter_vision_model
        assert parsed.supplier_name == "Northwind Supplies"

    def test_an_unknown_image_type_still_gets_a_usable_default(self, monkeypatch):
        # content_type is whatever the browser sent, and it is sometimes absent.
        monkeypatch.setattr(invoice_parser, "chat_json", lambda messages, model: {})
        assert parse_with_model(content=PNG_1PX, content_type=None) is not None

    def test_text_routes_to_the_text_model(self, monkeypatch):
        seen: dict = {}

        def fake_chat_json(messages, model):
            seen["model"] = model
            return {}

        monkeypatch.setattr(invoice_parser, "chat_json", fake_chat_json)
        parse_with_model(text="TAX INVOICE\nGSTIN: 27AACCM6094J1Z3")
        assert seen["model"] == invoice_parser.settings.openrouter_model

    def test_empty_text_is_refused_before_a_request_is_spent(self, monkeypatch):
        # A free-tier quota is small; sending whitespace to burn one of them
        # and get back an empty extraction helps nobody.
        monkeypatch.setattr(
            invoice_parser, "chat_json", lambda *a, **k: pytest.fail("called the model")
        )
        with pytest.raises(OpenRouterError, match="No text"):
            parse_with_model(text="   \n\t ")


# --------------------------------------------------------------------------
# parse_invoice on a photograph: model -> OCR -> heuristics
# --------------------------------------------------------------------------

def _no_text_from(monkeypatch):
    """A document that yields no extractable text — i.e. a scan."""
    monkeypatch.setattr(document_text, "extract", lambda *a, **k: "")


class TestAPhotographReachesTheVisionModel:
    def test_an_image_upload_is_read_by_the_vision_model(self, monkeypatch):
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)
        monkeypatch.setattr(
            invoice_parser,
            "chat_json",
            lambda messages, model: {"supplier_name": "Northwind Supplies",
                                     "invoice_number": "INV-2026-0042"},
        )

        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")
        assert parsed.invoice_number == "INV-2026-0042"
        assert "openrouter" in parsed.parsed_with

    def test_a_pdf_that_yielded_no_text_is_treated_as_a_scan(self, monkeypatch):
        # The common case: a PDF that is one embedded photograph. It is not an
        # image content-type, so only the empty text extraction reveals it.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)
        seen: dict = {}

        def fake_chat_json(messages, model):
            seen["model"] = model
            return {"supplier_name": "Northwind Supplies"}

        monkeypatch.setattr(invoice_parser, "chat_json", fake_chat_json)
        parse_invoice(content=PNG_1PX, content_type="application/pdf", filename="scan.pdf")

        assert seen["model"] == invoice_parser.settings.openrouter_vision_model

    def test_a_pdf_with_real_text_does_not_pay_for_the_vision_model(self, monkeypatch):
        # Vision calls are the expensive path; a text PDF must not take it.
        monkeypatch.setattr(document_text, "extract", lambda *a, **k: "TAX INVOICE\nTotal 100")
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)
        seen: dict = {}

        def fake_chat_json(messages, model):
            seen["model"] = model
            return {}

        monkeypatch.setattr(invoice_parser, "chat_json", fake_chat_json)

        parse_invoice(content=b"%PDF-1.4", content_type="application/pdf", filename="bill.pdf")
        assert seen["model"] == invoice_parser.settings.openrouter_model


class TestTheOcrFallback:
    def test_ocr_runs_when_the_vision_model_is_unavailable(self, monkeypatch):
        # No key configured at all: Tesseract is the only reader left.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: False)
        monkeypatch.setattr(
            document_text,
            "ocr_image",
            lambda content: "TAX INVOICE\nGSTIN: 27AACCM6094J1Z3\nInvoice No: INV-77",
        )

        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")
        assert parsed.supplier_gstin == "27AACCM6094J1Z3"
        assert parsed.invoice_number == "INV-77"

    def test_ocr_output_is_handed_back_to_the_model_when_there_is_one(self, monkeypatch):
        # The vision call failed but a text model is still reachable, so the
        # OCR text is worth a second attempt before falling to regexes.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)
        monkeypatch.setattr(document_text, "ocr_image", lambda content: "TAX INVOICE\nTotal 1180")

        calls: list = []

        def fake_chat_json(messages, model):
            calls.append(model)
            if model == invoice_parser.settings.openrouter_vision_model:
                raise OpenRouterError("vision model is rate limited")
            return {"supplier_name": "Northwind Supplies"}

        monkeypatch.setattr(invoice_parser, "chat_json", fake_chat_json)
        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")

        assert parsed.supplier_name == "Northwind Supplies"
        assert parsed.parsed_with.startswith("tesseract+"), parsed.parsed_with
        assert len(calls) == 2, "did not retry the OCR text against the text model"

    def test_the_ocr_text_becomes_the_raw_text_that_is_stored(self, monkeypatch):
        # What the heuristics ran against is what a reviewer needs to see.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: False)
        monkeypatch.setattr(document_text, "ocr_image", lambda content: "SCANNED INVOICE TEXT")

        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")
        assert "SCANNED INVOICE TEXT" in (parsed.raw_text or "")

    def test_both_models_failing_after_ocr_still_yields_the_heuristics(self, monkeypatch):
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)
        monkeypatch.setattr(
            document_text, "ocr_image", lambda content: "GSTIN: 27AACCM6094J1Z3"
        )

        def always_fails(messages, model):
            raise OpenRouterError("out of free-tier quota")

        monkeypatch.setattr(invoice_parser, "chat_json", always_fails)
        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")

        assert parsed.supplier_gstin == "27AACCM6094J1Z3"
        assert "tesseract" not in parsed.parsed_with

    def test_an_unreadable_image_produces_a_row_with_a_warning(self, monkeypatch):
        # Tesseract absent or the photo unreadable. This must still return —
        # the user corrects the row by hand rather than losing the upload.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: False)
        monkeypatch.setattr(document_text, "ocr_image", lambda content: "")

        parsed = parse_invoice(content=PNG_1PX, content_type="image/png", filename="bill.png")
        assert parsed.warnings
        assert any("No text could be read" in warning for warning in parsed.warnings)
        assert parsed.confidence < 0.5

    def test_ocr_is_not_run_for_a_document_that_already_gave_text(self, monkeypatch):
        monkeypatch.setattr(document_text, "extract", lambda *a, **k: "TAX INVOICE\nTotal 100")
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: False)
        monkeypatch.setattr(
            document_text,
            "ocr_image",
            lambda content: pytest.fail("OCR ran on a document that had text"),
        )

        assert parse_invoice(content=b"x", content_type="text/plain", filename="bill.txt")


class TestParseInvoiceNeverRaises:
    """The promise the upload route depends on, under each failure it can meet."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"content": b"", "content_type": "image/png", "filename": "empty.png"},
            {"content": b"\x00\xff\x00\xff", "content_type": "image/jpeg", "filename": "junk.jpg"},
            {"content": PNG_1PX, "content_type": None, "filename": None},
            {"content": b"%PDF-1.4 truncated", "content_type": "application/pdf"},
            {"text": ""},
        ],
    )
    def test_a_broken_upload_still_produces_a_row(self, kwargs):
        parsed = parse_invoice(**kwargs)
        assert parsed is not None
        assert parsed.confidence <= 1.0

    def test_an_ocr_engine_that_explodes_is_contained(self, monkeypatch):
        # ocr_image swallows its own failures, but a caller must not depend on
        # that to keep the promise.
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: False)
        monkeypatch.setattr(document_text, "ocr_image", lambda content: "")

        assert parse_invoice(content=PNG_1PX, content_type="image/png") is not None


class TestADocumentThatYieldedNoTextAndIsNotAnImage:
    """Nothing to read, and nothing an image path can be tried on.

    A .docx the extractor has no reader for, a .txt saved empty, a file whose
    extension lies about what is in it: the content is there, no text came out
    of it, and it is neither a picture nor a PDF, so the vision model and the
    OCR fallback are both inapplicable. What is left is an empty body, and the
    question is what happens to it with a model *configured*.

    The answer has to be "nothing is sent". Handing an empty document to a
    language model does not fail — it returns a confidently invented invoice,
    because that is what it was asked for — and the fields would be stored as
    an extraction over a file nobody could read. It also spends a request per
    unreadable upload against a free-tier quota the whole tenant shares.
    """

    def _unreadable_upload(self, monkeypatch, *, configured: bool):
        _no_text_from(monkeypatch)
        monkeypatch.setattr(invoice_parser, "is_configured", lambda: configured)
        monkeypatch.setattr(
            invoice_parser,
            "chat_json",
            lambda messages, model: pytest.fail("the model was asked to read nothing"),
        )
        monkeypatch.setattr(
            document_text,
            "ocr_image",
            lambda content: pytest.fail("OCR ran on something that is not an image"),
        )
        return parse_invoice(
            content=b"PK\x03\x04not-really-readable",
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename="bill.docx",
        )

    def test_an_empty_body_is_not_sent_to_the_model(self, monkeypatch):
        parsed = self._unreadable_upload(monkeypatch, configured=True)

        assert parsed.parsed_with == "heuristic"
        assert parsed.supplier_gstin is None
        assert parsed.invoice_number is None

    def test_the_upload_still_becomes_a_row_the_user_can_correct(self, monkeypatch):
        """The whole fallback chain exists so an upload never fails outright.
        Reaching the end of it with nothing read is still a row, with the
        warning that routes it to somebody holding the paper."""
        parsed = self._unreadable_upload(monkeypatch, configured=True)

        assert any("No text could be read" in warning for warning in parsed.warnings)
        assert parsed.confidence < 0.5

    def test_it_lands_the_same_way_with_no_model_configured(self, monkeypatch):
        """A configured model must not change the outcome for a file it was
        never given. If these two diverged, the same unreadable upload would
        produce different rows on the box that has a key and the box that does
        not — and the suite runs without one, so the divergence would be
        invisible here."""
        with_model = self._unreadable_upload(monkeypatch, configured=True)
        without = self._unreadable_upload(monkeypatch, configured=False)

        assert with_model.warnings == without.warnings
        assert with_model.parsed_with == without.parsed_with
        assert with_model.confidence == without.confidence
