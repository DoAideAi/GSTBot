"""Extraction: the heuristic path, the model path, and the validation between."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import filing as filing_service
from app.services import gst_calendar, invoice_parser
from app.services.invoice_parser import (
    ParsedInvoice,
    _from_model_payload,
    parse_heuristic,
    parse_invoice,
    to_date,
    to_decimal,
    to_money,
    validate,
)
from app.services.openrouter_client import OpenRouterError, extract_json_object
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE

# What an unread tax head is left as, which is what several of the tax-line
# tests below are about: a blank a reviewer can see, rather than a guess.
ZERO = Decimal("0.00")

INTRASTATE_INVOICE = f"""\
MUMBAI HARDWARE SUPPLIES
GSTIN: {SUPPLIER_GSTIN_SAME_STATE}
TAX INVOICE
Invoice No: MH/2026/118
Invoice Date: 02/05/2026
Bill To: UMANG TRADERS  GSTIN: {BUSINESS_GSTIN}
HSN: 73181500
Taxable Value: 100000.00
CGST @ 9%: 9000.00
SGST @ 9%: 9000.00
Grand Total: 118000.00
"""


# --------------------------------------------------------------------------
# Coercion
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,23,456.78", Decimal("123456.78")),  # Indian digit grouping.
        ("₹ 45,000", Decimal("45000")),
        ("Rs. 1000.50", Decimal("1000.50")),
        (1234.5, Decimal("1234.5")),
        (0, Decimal("0")),
        (None, Decimal("0.00")),
        ("", Decimal("0.00")),
        ("not a number", Decimal("0.00")),
        ("-500.00", Decimal("-500.00")),
    ],
)
def test_to_decimal(raw, expected):
    assert to_decimal(raw) == expected


def test_to_decimal_honours_a_none_default():
    assert to_decimal("garbage", default=None) is None


def test_to_decimal_does_not_treat_booleans_as_numbers():
    """``True`` is an ``int`` in Python, and ``Decimal(1)`` is not an amount."""
    assert to_decimal(True) == Decimal("0.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-15", date(2026, 4, 15)),
        ("15/04/2026", date(2026, 4, 15)),
        ("15-04-2026", date(2026, 4, 15)),
        ("15.04.2026", date(2026, 4, 15)),
        ("15-Apr-2026", date(2026, 4, 15)),
        ("15 April 2026", date(2026, 4, 15)),
        ("nonsense", None),
        ("", None),
        (None, None),
    ],
)
def test_to_date(raw, expected):
    assert to_date(raw) == expected


def test_ambiguous_dates_are_read_day_first():
    """``03/04/2026`` is 3 April in India, not 4 March."""
    assert to_date("03/04/2026") == date(2026, 4, 3)


# --------------------------------------------------------------------------
# Heuristic extraction
# --------------------------------------------------------------------------

def test_heuristic_reads_an_interstate_invoice(sample_invoice_text):
    parsed = parse_heuristic(sample_invoice_text)

    assert parsed.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE
    assert parsed.buyer_gstin == BUSINESS_GSTIN
    assert parsed.invoice_number == "INV-2026-0042"
    assert parsed.invoice_date == date(2026, 4, 15)
    assert parsed.period == "2026-04"
    assert parsed.hsn_code == "84713010"
    assert parsed.taxable_value == Decimal("450000.00")
    assert parsed.igst == Decimal("81000.00")
    assert parsed.total_value == Decimal("531000.00")
    assert parsed.parsed_with == "heuristic"


def test_heuristic_reads_an_intrastate_invoice():
    parsed = parse_heuristic(INTRASTATE_INVOICE)

    assert parsed.supplier_gstin == SUPPLIER_GSTIN_SAME_STATE
    assert parsed.cgst == Decimal("9000.00")
    assert parsed.sgst == Decimal("9000.00")
    assert parsed.igst == Decimal("0.00")
    assert parsed.total_value == Decimal("118000.00")


def test_heuristic_on_empty_text_is_empty_not_an_error():
    parsed = parse_heuristic("")
    assert parsed.supplier_gstin is None
    assert parsed.total_value == Decimal("0.00")
    assert parsed.confidence == 0.0


def test_heuristic_confidence_reflects_field_coverage():
    """Confidence is coverage, and is capped below certainty.

    Regexes match shape, not meaning, so even a fully-populated heuristic read
    must stay below a model's — it is what decides which invoices a human is
    asked to check.
    """
    full = parse_heuristic(INTRASTATE_INVOICE)
    sparse = parse_heuristic("Some text with no invoice fields at all")
    assert full.confidence > sparse.confidence
    assert full.confidence <= 0.6


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_validate_flags_an_unbalanced_total():
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        taxable_value=Decimal("1000.00"),
        igst=Decimal("180.00"),
        total_value=Decimal("1500.00"),  # Should be 1180.
        confidence=0.9,
    )
    validate(parsed)
    assert any("does not equal" in w for w in parsed.warnings)


def test_validate_tolerates_rupee_rounding():
    """Invoices round tax lines to the rupee; a few paise is not a defect."""
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        taxable_value=Decimal("1000.00"),
        igst=Decimal("180.00"),
        total_value=Decimal("1180.50"),
        confidence=0.9,
    )
    validate(parsed)
    assert not any("does not equal" in w for w in parsed.warnings)


def test_validate_rejects_igst_together_with_cgst():
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        cgst=Decimal("90.00"),
        igst=Decimal("180.00"),
    )
    validate(parsed)
    assert any("both IGST and CGST" in w for w in parsed.warnings)


def test_validate_flags_unequal_cgst_and_sgst():
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_SAME_STATE,
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        cgst=Decimal("90.00"),
        sgst=Decimal("80.00"),
    )
    validate(parsed)
    assert any("should be equal" in w for w in parsed.warnings)


def test_validate_flags_an_interstate_supply_taxed_as_cgst_sgst():
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,  # Karnataka
        buyer_gstin=BUSINESS_GSTIN,  # Maharashtra
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        cgst=Decimal("90.00"),
        sgst=Decimal("90.00"),
    )
    validate(parsed)
    assert any("Inter-state supply taxed as CGST/SGST" in w for w in parsed.warnings)


def test_validate_flags_an_intrastate_supply_taxed_as_igst():
    parsed = ParsedInvoice(
        supplier_gstin=SUPPLIER_GSTIN_SAME_STATE,  # Maharashtra
        buyer_gstin=BUSINESS_GSTIN,  # Maharashtra
        invoice_number="X-1",
        invoice_date=date(2026, 4, 1),
        igst=Decimal("180.00"),
    )
    validate(parsed)
    assert any("Intra-state supply taxed as IGST" in w for w in parsed.warnings)


def test_validate_accepts_a_correct_interstate_invoice(sample_invoice_text):
    parsed = validate(parse_heuristic(sample_invoice_text))
    assert parsed.warnings == []


def test_validate_lowers_confidence_per_warning():
    parsed = ParsedInvoice(confidence=0.9)
    validate(parsed)
    assert parsed.warnings
    assert parsed.confidence < 0.9


# --------------------------------------------------------------------------
# Model extraction
# --------------------------------------------------------------------------

def test_model_extraction_is_used_when_configured(stub_openrouter, sample_invoice_text):
    stub_openrouter.update(
        {
            "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
            "supplier_name": "Northwind Supplies Private Limited",
            "buyer_gstin": BUSINESS_GSTIN,
            "invoice_number": "INV-2026-0042",
            "invoice_date": "2026-04-15",
            "place_of_supply": "27",
            "hsn_code": "84713010",
            "taxable_value": 450000,
            "cgst": 0,
            "sgst": 0,
            "igst": 81000,
            "cess": 0,
            "total_value": 531000,
            "tax_rate": 18,
            "confidence": 0.95,
        }
    )
    parsed = parse_invoice(text=sample_invoice_text)

    assert parsed.parsed_with.startswith("openrouter:")
    assert parsed.supplier_name == "Northwind Supplies Private Limited"
    assert parsed.tax_rate == Decimal("18")
    assert parsed.place_of_supply == "27"
    assert parsed.confidence == pytest.approx(0.95)
    assert parsed.warnings == []


def test_a_hallucinated_gstin_is_discarded(stub_openrouter, sample_invoice_text):
    """A confident wrong GSTIN is worse than no GSTIN.

    It attributes the invoice to a different taxpayer, and everything
    downstream — the supplier record, the 2B match, the ITC claim — inherits
    the error silently. The check digit is the arbiter, not the model.
    """
    stub_openrouter.update(
        {
            "supplier_gstin": "27AAPFU0939F1ZW",  # Valid shape, bad check digit.
            "invoice_number": "INV-2026-0042",
            "invoice_date": "2026-04-15",
            "taxable_value": 450000,
            "igst": 81000,
            "total_value": 531000,
        }
    )
    parsed = parse_invoice(text=sample_invoice_text)

    assert parsed.supplier_gstin != "27AAPFU0939F1ZW"
    assert any("Discarded invalid" in w for w in parsed.warnings)
    # The heuristic pass then supplies the real one from the invoice text.
    assert parsed.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE


def test_heuristics_fill_gaps_the_model_left(stub_openrouter, sample_invoice_text):
    stub_openrouter.update(
        {
            "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
            "invoice_number": None,  # Model missed it.
            "invoice_date": None,
            "taxable_value": 450000,
            "igst": 81000,
            "total_value": 531000,
            "confidence": 0.8,
        }
    )
    parsed = parse_invoice(text=sample_invoice_text)

    assert parsed.invoice_number == "INV-2026-0042"
    assert parsed.invoice_date == date(2026, 4, 15)


def test_heuristics_do_not_overwrite_what_the_model_answered(
    stub_openrouter, sample_invoice_text
):
    """Gap-filling only.

    The regex has no notion of layout and would happily replace an invoice
    total with a line item's amount, so a field the model answered is final.
    """
    stub_openrouter.update(
        {
            "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
            "invoice_number": "MODEL-NUMBER",
            "invoice_date": "2026-04-15",
            "taxable_value": 450000,
            "igst": 81000,
            "total_value": 531000,
        }
    )
    assert parse_invoice(text=sample_invoice_text).invoice_number == "MODEL-NUMBER"


def test_an_out_of_range_tax_rate_is_dropped(stub_openrouter):
    """17% is not a GST rate, so it is a misread rather than a rate.

    The invoice text here prints no percentage, so nothing can refill the
    field and the drop is observable on its own.
    """
    text = f"ACME LTD GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}\nInvoice No: A-9\nTotal Amount: 1180.00"
    stub_openrouter.update(
        {"supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE, "tax_rate": 17, "total_value": 1180}
    )
    assert parse_invoice(text=text).tax_rate is None


def test_a_dropped_rate_is_refilled_from_the_document(stub_openrouter, sample_invoice_text):
    """Dropping the model's answer is not the same as giving up on the field.

    The invoice itself says 18%, so the heuristic pass supplies it once the
    model's impossible 17 has been discarded.
    """
    stub_openrouter.update(
        {"supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE, "tax_rate": 17, "total_value": 531000}
    )
    assert parse_invoice(text=sample_invoice_text).tax_rate == Decimal("18")


def test_heuristic_sums_the_two_halves_of_an_intrastate_rate():
    """An 18% invoice prints as 9% CGST + 9% SGST.

    Reporting 9 would understate the rate on every intra-state invoice.
    """
    assert parse_heuristic(INTRASTATE_INVOICE).tax_rate == Decimal("18")


def test_heuristic_does_not_read_gstin_as_a_tax_line():
    """"GSTIN" contains "GST".

    A label pattern that is not anchored on word boundaries reads the digits
    of the GSTIN itself as an SGST amount.
    """
    parsed = parse_heuristic(f"GSTIN: {SUPPLIER_GSTIN_SAME_STATE}\nTotal Amount: 1000.00")
    assert parsed.sgst == Decimal("0.00")
    assert parsed.cgst == Decimal("0.00")


def test_a_fractional_rate_is_read_as_a_percentage(stub_openrouter, sample_invoice_text):
    """A model asked for "18" sometimes answers "0.18"."""
    stub_openrouter.update(
        {"supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE, "tax_rate": 0.18, "total_value": 531000}
    )
    assert parse_invoice(text=sample_invoice_text).tax_rate == Decimal("18")


class TestTheParserAndTheFilingValidatorAgreeOnTheSlabs:
    """One list of what GST charges, not two that drift.

    The parser's list was short 0.1%, 1%, 1.5%, 6% and 7.5%. An invoice on one
    of those had its rate discarded here as impossible, and reached filing with
    the field empty — where filing's "tax does not match rate x taxable value"
    check is skipped for want of a rate to apply. The invoices whose rate the
    product could not read were exactly the ones whose arithmetic it never
    verified.
    """

    def test_there_is_only_one_definition(self):
        assert filing_service.VALID_RATES is invoice_parser.VALID_TAX_RATES

    @pytest.mark.parametrize(
        "rate", ["0.1", "1", "1.5", "6", "7.5"]
    )
    def test_a_slab_the_parser_used_to_drop_now_survives(self, rate):
        assert invoice_parser.normalize_rate(rate) == Decimal(rate)

    def test_an_affordable_housing_invoice_keeps_its_rate(self):
        """1.5% is printed as 0.75% CGST plus 0.75% SGST."""
        text = (
            "CGST @ 0.75%   750.00\n"
            "SGST @ 0.75%   750.00\n"
            "Taxable Value: 100000.00\n"
        )
        assert parse_heuristic(text).tax_rate == Decimal("1.5")

    def test_a_rate_that_is_not_a_slab_is_still_dropped(self):
        """Completing the list must not turn it into "anything goes"."""
        assert invoice_parser.normalize_rate("17") is None
        assert invoice_parser.normalize_rate("20") is None
        assert invoice_parser.normalize_rate("15") is None


class TestTheSubOnePercentSlabs:
    """A rate below 1% is a rate, not a fraction to be scaled.

    ``0.25`` is a real GST rate and sits in the parser's own list of them.
    Scaling every sub-1 value before checking that list turned it into 25 —
    which is not a slab — and dropped it, so an invoice on rough diamonds could
    never carry the rate it plainly printed.
    """

    def test_a_quarter_percent_survives(self):
        assert invoice_parser.normalize_rate("0.25") == Decimal("0.25")

    def test_it_is_still_a_rate_when_it_arrives_as_a_number(self):
        assert invoice_parser.normalize_rate(0.25) == Decimal("0.25")

    def test_a_fraction_that_is_not_itself_a_rate_is_still_scaled(self):
        """Reading the literal first must not stop 0.18 meaning 18%."""
        assert invoice_parser.normalize_rate("0.18") == Decimal("18")
        assert invoice_parser.normalize_rate("0.05") == Decimal("5")

    def test_a_fraction_of_a_rate_that_is_not_one_is_still_dropped(self):
        """0.5 is neither a slab nor a fraction of one; 50% does not exist."""
        assert invoice_parser.normalize_rate("0.5") is None

    def test_the_two_readings_never_both_land_on_a_slab(self):
        """Why preferring the literal costs nothing.

        If some value were a slab both as itself and as a fraction, the
        preference would be a guess. None is, so it is not.
        """
        both = [
            rate
            for rate in invoice_parser.VALID_TAX_RATES
            if Decimal("0") < rate < Decimal("1") and rate * 100 in invoice_parser.VALID_TAX_RATES
        ]
        assert both == []

    def test_a_quarter_percent_invoice_keeps_its_rate_end_to_end(
        self, stub_openrouter, sample_invoice_text
    ):
        stub_openrouter.update(
            {
                "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
                "tax_rate": 0.25,
                "total_value": 531000,
            }
        )
        assert parse_invoice(text=sample_invoice_text).tax_rate == Decimal("0.25")


def test_a_model_failure_falls_back_to_heuristics(monkeypatch, sample_invoice_text):
    """A free-tier rate limit must not lose an invoice."""
    monkeypatch.setattr(invoice_parser, "is_configured", lambda: True)

    def _boom(*args, **kwargs):
        raise OpenRouterError("429 rate limited")

    monkeypatch.setattr(invoice_parser, "chat_json", _boom)

    parsed = parse_invoice(text=sample_invoice_text)
    assert parsed.parsed_with == "heuristic"
    assert parsed.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE
    assert parsed.total_value == Decimal("531000.00")


def test_parse_invoice_without_a_key_uses_heuristics(sample_invoice_text):
    parsed = parse_invoice(text=sample_invoice_text)
    assert parsed.parsed_with == "heuristic"
    assert parsed.invoice_number == "INV-2026-0042"


def test_parse_invoice_never_raises_on_junk():
    parsed = parse_invoice(content=b"\x00\x01\x02", content_type="image/png", filename="x.png")
    assert isinstance(parsed, ParsedInvoice)
    assert parsed.warnings  # It says what went wrong rather than throwing.


def test_parse_invoice_reads_a_plain_text_upload(sample_invoice_text):
    parsed = parse_invoice(
        content=sample_invoice_text.encode(), content_type="text/plain", filename="inv.txt"
    )
    assert parsed.invoice_number == "INV-2026-0042"


def test_as_dict_is_json_safe(sample_invoice_text):
    import json

    data = parse_invoice(text=sample_invoice_text).as_dict()
    json.dumps(data)  # Must not raise: this is stored in a JSON column.
    assert data["invoice_date"] == "2026-04-15"
    assert data["taxable_value"] == "450000.00"


# --------------------------------------------------------------------------
# JSON extraction from model output
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        '{"invoice_number": "A-1"}',
        '```json\n{"invoice_number": "A-1"}\n```',
        'Here is the result:\n{"invoice_number": "A-1"}\nHope that helps.',
        'We need to read the invoice. The user wants JSON. {"invoice_number": "A-1"}',
    ],
)
def test_extract_json_object_survives_free_tier_output(raw):
    assert extract_json_object(raw) == {"invoice_number": "A-1"}


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2, 3]", "{not valid json}"])
def test_extract_json_object_returns_none_when_there_is_none(raw):
    assert extract_json_object(raw) is None


class TestADateNoInvoiceCouldCarry:
    """The one field whose typo removes the invoice instead of misstating it.

    The filing period is derived from ``invoice_date``, so a year misread out
    of a scan does not put a wrong figure on a return — it puts the invoice in
    a month no return covers, and it leaves the register, the dashboard and the
    GSTR-1 in one step. Nothing downstream is left to notice, because every
    check there is scoped to a period and this invoice is no longer in one.

    A warning rather than a discard, as everything in ``validate`` is: the
    lowered confidence is what routes it to the reviewer holding the paper.
    """

    @staticmethod
    def _dated(day: date) -> ParsedInvoice:
        return ParsedInvoice(
            supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
            invoice_number="X-1",
            invoice_date=day,
        )

    def test_a_slipped_century_is_flagged(self):
        parsed = validate(self._dated(date(2099, 1, 15)))
        assert any("outside the span" in w for w in parsed.warnings)
        assert any("2099-01-15" in w for w in parsed.warnings)

    def test_a_date_before_gst_existed_is_flagged(self):
        parsed = validate(self._dated(date(2016, 4, 15)))
        assert any("outside the span" in w for w in parsed.warnings)

    def test_a_date_within_the_span_is_not_flagged(self):
        parsed = validate(self._dated(date(2026, 4, 15)))
        assert not any("outside the span" in w for w in parsed.warnings)

    def test_the_day_gst_commenced_is_itself_within_the_span(self):
        parsed = validate(self._dated(gst_calendar.GST_COMMENCEMENT))
        assert not any("outside the span" in w for w in parsed.warnings)

    def test_today_is_within_the_span(self):
        parsed = validate(self._dated(gst_calendar.today_ist()))
        assert not any("outside the span" in w for w in parsed.warnings)

    def test_tomorrow_is_not(self):
        parsed = validate(
            self._dated(gst_calendar.today_ist() + timedelta(days=1))
        )
        assert any("outside the span" in w for w in parsed.warnings)

    def test_the_flag_lowers_confidence_so_a_human_sees_it(self):
        parsed = self._dated(date(2099, 1, 15))
        parsed.confidence = 0.95
        validate(parsed)
        assert parsed.confidence < 0.95

    def test_a_missing_date_still_reports_only_that(self):
        """Absent and impossible are different problems; one message each."""
        parsed = validate(self._dated(None))
        assert any("No invoice date found" in w for w in parsed.warnings)
        assert not any("outside the span" in w for w in parsed.warnings)


# --------------------------------------------------------------------------
# The labels a real document puts in front of a number and a date
# --------------------------------------------------------------------------

class TestTheInvoiceNumberSurvivesItsLabel:
    """A prefixed number must come back whole, whatever the label looks like.

    These all used to come back as the tail alone — "INV-001" read as "001" —
    because a label the pattern could not match did not end the search. It
    slid on and matched the ``inv`` alternative against the *value*, taking
    the hyphen inside the number as the separator it had been looking for.

    A truncated number is worse than a missing one and there is nothing
    downstream to catch it. It goes into GSTR-1 as ``inum``, which is the
    customer's evidence for their own credit; reconciliation matches a
    GSTR-2B row on it, so the supplier's real invoice reports as missing from
    the 2B; and duplicate detection keys on it, so the same document uploaded
    twice no longer looks like the same document.
    """

    @staticmethod
    def _number(line: str) -> str | None:
        return parse_heuristic(f"TAX INVOICE\n{line}\nTaxable Value: 100.00\n").invoice_number

    @pytest.mark.parametrize(
        "line",
        [
            "Invoice No: INV-001",
            "Invoice No.: INV-001",
            "Invoice No. INV-001",
            "Invoice No INV-001",
            "Invoice Number: INV-001",
            "Invoice Number INV-001",
            "Invoice #: INV-001",
            "Invoice # INV-001",
            "Invoice No.:INV-001",
            "Invoice No :- INV-001",
            "Invoice No -: INV-001",
            "INVOICE NO. : INV-001",
            "Inv No.: INV-001",
            "Inv. No.: INV-001",
            "Bill No.: INV-001",
            "Bill No: INV-001",
            "Invoice: INV-001",
        ],
    )
    def test_a_prefixed_number_is_not_truncated_to_its_digits(self, line):
        assert self._number(line) == "INV-001"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # A slash-separated series number, which is the other common shape.
            ("Invoice No.: TS/26-27/119", "TS/26-27/119"),
            ("Invoice No.: INV/2026/007", "INV/2026/007"),
            # The prefix is itself a label word — the case most likely to be
            # eaten by a pattern that searches for one.
            ("Invoice No.: BILL-99", "BILL-99"),
            ("Invoice No.: 2026-0042", "2026-0042"),
        ],
    )
    def test_a_number_that_looks_like_a_label_is_still_read_whole(self, line, expected):
        assert self._number(line) == expected

    @pytest.mark.parametrize(
        "text",
        [
            # No label at all. Leaving the field empty is the point: a bare
            # "INV-001" in the body used to parse as the number "001", and a
            # plausible wrong number is not a state a reviewer can see is
            # wrong. An empty one carries "No invoice number found".
            "TAX INVOICE\nINV-001\n",
            # The letterhead under a bare "TAX INVOICE" heading is not a number.
            "TAX INVOICE\nACME STEELS PVT LTD\n",
            "Bill To: BUILDCO LIMITED\n",
        ],
    )
    def test_nothing_is_invented_where_there_is_no_label(self, text):
        assert parse_heuristic(text).invoice_number is None

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # How a business in its first months of trading numbers an invoice.
            ("Invoice No: 7", "7"),
            ("Invoice Number: 1", "1"),
            ("Bill No: 5", "5"),
            ("Invoice No.: A", "A"),
            ("Invoice # 9", "9"),
        ],
    )
    def test_a_one_character_number_is_a_number(self, line, expected):
        """A series that has not reached double figures yet.

        The value had a two-character floor, so every one of these came back
        empty — silently, because there is nothing left to look at afterwards.
        It is the same loss as a truncated number and it fails in the same
        three places: ``inum: ""`` is a GSTR-1 the portal rejects, the supplier's
        2B row matches nothing, and the natural key duplicate detection uses is
        half missing.
        """
        assert self._number(line) == expected

    def test_an_explicit_label_is_still_what_makes_one_character_safe(self):
        """The floor only lifts behind a "no"/"number"/"#" token.

        Without one there is no evidence a label was read at all, and a single
        stray character after a full stop is noise rather than a document
        number — which is the reading the whole pattern is built to refuse.
        """
        assert self._number("Invoice. X") is None
        assert self._number("Invoice: 7") is None


class TestWhichDateOnTheInvoiceIsTheInvoiceDate:
    @staticmethod
    def _date(text: str):
        return parse_heuristic(text).invoice_date

    @pytest.mark.parametrize(
        "line",
        [
            "Invoice Date: 15/04/2026",
            "Invoice Date.: 15/04/2026",
            "Invoice Date : 15/04/2026",
            "INVOICE DATE.:15/04/2026",
            "Date of Invoice: 15/04/2026",
            "Date of Issue: 15/04/2026",
            "Bill Date: 15/04/2026",
            "Date: 15/04/2026",
            "Dated : 15.04.2026",
        ],
    )
    def test_the_label_may_be_written_any_of_the_usual_ways(self, line):
        assert self._date(f"TAX INVOICE\n{line}\n") == date(2026, 4, 15)

    def test_a_due_date_printed_first_does_not_become_the_invoice_date(self):
        """The period is derived from this field, so the wrong date is a wrong return.

        A payment due date is normally printed *above* the invoice date, and a
        bare ``date`` label matches "Due Date" as readily as "Invoice Date" —
        so the leftmost match was the due date. The invoice then filed under
        the month it had to be paid in rather than the month it was issued in.
        """
        parsed = parse_heuristic(
            "TAX INVOICE\n"
            "Due Date: 15/05/2026\n"
            "Invoice Date: 15/04/2026\n"
        )
        assert parsed.invoice_date == date(2026, 4, 15)
        assert parsed.period == "2026-04"

    def test_a_due_date_printed_first_does_not_beat_date_of_issue_either(self):
        """The rule-46(f) wording is as explicit as "Invoice Date", not a fallback.

        A template built against the rule text prints "Date of Issue" rather
        than "Invoice Date", and it deserves the same priority over a due date
        printed above it — not the loose pattern's mere leftmost-wins.
        """
        parsed = parse_heuristic(
            "TAX INVOICE\n"
            "Due Date: 15/05/2026\n"
            "Date of Issue: 15/04/2026\n"
        )
        assert parsed.invoice_date == date(2026, 4, 15)
        assert parsed.period == "2026-04"

    def test_a_due_date_alone_is_still_read_rather_than_dropped(self):
        """The loose label stays a fallback: some documents only say "Date"."""
        assert self._date("TAX INVOICE\nDue Date: 15/05/2026\n") == date(2026, 5, 15)

    def test_a_due_date_does_not_beat_the_bare_label_the_document_uses(self):
        """Ordering the two patterns only answers this when the explicit one matches.

        The document above prints "Invoice Date" and so is decided by which
        label wins. Most do not: they label their own date "Date:", which is
        the case the loose pattern exists for, and against that the due date
        was still printed first and still won on being leftmost. The period is
        derived from this field, so it filed one month late — the same wrong
        return the explicit label was added to prevent, on the commoner layout.
        """
        parsed = parse_heuristic(
            "TAX INVOICE\n"
            "Due Date: 15/05/2026\n"
            "Date: 15/04/2026\n"
        )
        assert parsed.invoice_date == date(2026, 4, 15)
        assert parsed.period == "2026-04"

    @pytest.mark.parametrize(
        ("label", "printed"),
        [
            # The e-invoice acknowledgement, which follows the invoice.
            ("Ack Date", "16/04/2026"),
            ("Acknowledgement Date", "16/04/2026"),
            # The consignment's own paperwork, printed in the same block.
            ("E-Way Bill Date", "16/04/2026"),
            ("LR Date", "16/04/2026"),
            ("Transport Date", "16/04/2026"),
            # Documents that predate the supply, by a quarter on a slow order.
            ("PO Date", "02/01/2026"),
            ("P.O. Date", "02/01/2026"),
            ("Order Date", "02/01/2026"),
            ("Challan Date", "14/04/2026"),
            ("Delivery Date", "17/04/2026"),
            # Rule 47 gives thirty days to invoice a supply, so these differ.
            ("Supply Date", "31/03/2026"),
            # And the two ends of the money.
            ("Due Date", "15/05/2026"),
            ("Payment Date", "20/05/2026"),
        ],
    )
    def test_another_dates_label_does_not_take_the_bare_one(self, label, printed):
        """An invoice prints several dates and only the date of issue is this field.

        Each of these is printed on the face of an ordinary invoice, above the
        document's own date as often as not, and each was read as the invoice
        date by whichever pattern reached it first. They are wrong by days or
        by months depending on the label, and a month is a wrong return.
        """
        assert self._date(f"TAX INVOICE\n{label}: {printed}\nDate: 15/04/2026\n") == date(
            2026, 4, 15
        )

    def test_the_e_way_bills_date_does_not_beat_an_explicit_invoice_date(self):
        """"E-Way Bill Date" ends in "Bill Date", which is an invoice-date label.

        So this one was not a case of the loose pattern reaching too far: the
        explicit pattern matched the transport document's date itself, and
        preferring the explicit label picked the wrong date faster.
        """
        parsed = parse_heuristic(
            "TAX INVOICE\n"
            "E-Way Bill Date: 16/04/2026\n"
            "Invoice Date: 15/04/2026\n"
        )
        assert parsed.invoice_date == date(2026, 4, 15)

    @pytest.mark.parametrize(
        "citation",
        [
            "Original Invoice Date: 02/01/2026",
            "Against our Invoice Date: 02/01/2026",
            "Ref: Invoice Date: 02/01/2026",
            "w.r.t. Invoice Date: 02/01/2026",
            "Vide Bill Date: 02/01/2026",
        ],
    )
    def test_a_cited_documents_date_does_not_become_this_ones(self, citation):
        """A credit note carries the original invoice's date under rule 53.

        Which puts a second, older date above the note's own — the same shape
        as the cited *number* this module already passes over, and it lands the
        same way. The cited date is a real date belonging to a real earlier
        document, so nothing downstream has reason to look twice at a note
        filed in the period the invoice it cancels was issued in.
        """
        assert self._date(f"CREDIT NOTE\n{citation}\nDate: 15/04/2026\n") == date(2026, 4, 15)

    def test_a_marked_date_is_still_read_when_it_is_the_only_one(self):
        """Passing over a marked date decides precedence, not admissibility.

        A document whose only date is marked still gets one — dropping it would
        trade a date that is probably a month out for no date at all, and the
        loose label exists because some documents are printed that carelessly.
        """
        assert self._date("TAX INVOICE\nPO Date: 02/01/2026\n") == date(2026, 1, 2)

    def test_a_value_that_does_not_parse_does_not_blank_the_field(self):
        """The pattern matches a date-shaped string, which is not the same as a date.

        Taking the first match and stopping meant one unreadable value left the
        field empty with the real date printed two lines below it.
        """
        assert self._date("TAX INVOICE\nDate: 12/ABC/34\nInvoice Date: 15/04/2026\n") == date(
            2026, 4, 15
        )

    def test_an_unparseable_marked_date_does_not_end_the_second_pass_either(self):
        """The same rule has to hold on the fallback tier, and holds separately.

        The two tiers are two loops and only the first was covered. This is the
        shape a scanned delivery-and-payment slip actually has: every date on
        it is marked, so the first pass yields nothing and the second decides —
        and the topmost is the one the OCR mangled, a smudged month being the
        single commonest thing to lose off a scan.

        Stopping at the first unreadable marked value files this document with
        no date at all, which is worse than filing it with one a few weeks out:
        the period is derived from this field, so the invoice lands in no
        return rather than in an adjacent one.
        """
        assert self._date(
            "TAX INVOICE\nDue Date: 12/ABC/34\nPayment Date: 20/05/2026\n"
        ) == date(2026, 5, 20)

    def test_a_document_whose_dates_are_all_unreadable_gets_none(self):
        """And the second pass still has to end empty-handed rather than
        settle. ``None`` is what the warning downstream is raised from; a date
        invented here would file the invoice under a month nobody chose and
        nothing would flag it."""
        assert self._date("TAX INVOICE\nDue Date: 12/ABC/34\nPO Date: 99/XY/00\n") is None


class TestOneLineThatNamesTwoTaxHeads:
    """A line can name CGST and SGST at once, and the two ways it does are opposites.

    Either it lays them out side by side, with a figure each, or it *combines*
    them into one figure that is the total of both. Read a head at a time —
    which is how tax has to be read, because the label, the rate and the amount
    share a line — the second shape put the whole combined figure onto each
    head and doubled the tax on the invoice at the moment of extraction.

    Doubled tax is not a display problem in either direction: on a purchase it
    doubles the credit claimed, and on a sale it doubles what the business is
    told to pay. Nothing downstream re-derives the arithmetic on the invoice,
    so every screen agreed with every other one.
    """

    @staticmethod
    def _heads(text: str) -> tuple:
        parsed = parse_heuristic(f"TAX INVOICE\nTaxable Value: 100000.00\n{text}\n")
        return parsed.cgst, parsed.sgst, parsed.igst, parsed.cess

    @pytest.mark.parametrize(
        "line",
        [
            "Total Tax (CGST + SGST): 18000.00",
            "CGST + SGST: 18000.00",
            "CGST & SGST @ 18%: 18000.00",
            "Add: CGST/SGST 18000.00",
        ],
    )
    def test_a_combined_figure_is_not_given_to_both_heads(self, line):
        # One figure for two heads is the total of both. Split, it is doubled;
        # halved, it is a guess. Left unread, it is a blank a reviewer can see
        # and `validate_period` complains that the invoice does not foot.
        assert self._heads(line) == (ZERO, ZERO, ZERO, ZERO)

    def test_heads_laid_out_side_by_side_are_both_read(self):
        # The opposite shape, and the reason a combined line cannot simply be
        # detected by "two labels on one line".
        assert self._heads("CGST 9% 9000.00 SGST 9% 9000.00") == (
            Decimal("9000.00"),
            Decimal("9000.00"),
            ZERO,
            ZERO,
        )

    def test_each_head_is_read_from_its_own_column(self):
        # Taking the last number on the line for both heads is right only by
        # the accident that CGST and SGST are equal. Nothing enforces that here
        # — a mis-keyed register is exactly when a reviewer needs to see the
        # two figures differ rather than have one silently overwrite the other.
        assert self._heads("CGST 9% 9000.00 SGST 9% 8000.00") == (
            Decimal("9000.00"),
            Decimal("8000.00"),
            ZERO,
            ZERO,
        )

    def test_a_head_whose_own_column_holds_no_figure_reads_nothing(self):
        """Both labels first, then both figures — a column *header* run into
        its values, which is what a tax table OCRs to when the rules between
        the cells are lost.

        There are two amounts and two heads, so the shortfall guard that
        catches a combined line lets this through; the column cut then leaves
        CGST with ``"CGST "`` and no figure in it. Reading nothing there is the
        point. The figures are equal here only by convention, and the head
        whose column is empty has no claim on its neighbour's amount — taking
        the last number on the line would give CGST the SGST figure and be
        wrong in exactly the cases (unequal heads, a cess column) where anyone
        would notice.

        Half a line read is still a line that does not foot, which is what
        ``validate_period`` is for and what puts it in front of a reviewer.
        """
        assert self._heads("CGST SGST 9,000.00 9,000.00") == (
            ZERO,
            Decimal("9000.00"),
            ZERO,
            ZERO,
        )

    def test_a_header_row_above_its_values_reads_no_tax_at_all(self):
        # The same table with the line break intact. Neither label shares a
        # line with a figure, so neither head is read rather than both being
        # taken from the row below — the failure `_amount_on_line`'s money
        # shape test and `TestALabelWithNothingBesideItReadsNoNumber` are both
        # about, reached here through the tax reader instead.
        assert self._heads("CGST SGST\n9,000.00 9,000.00") == (ZERO, ZERO, ZERO, ZERO)

    def test_a_rate_printed_without_a_percent_sign_is_not_read_as_the_amount(self):
        # The column search must still prefer the last figure inside its own
        # column, because "9" here is a rate with no percent sign to strip.
        assert self._heads("CGST 9 9000.00 SGST 9 9000.00") == (
            Decimal("9000.00"),
            Decimal("9000.00"),
            ZERO,
            ZERO,
        )

    def test_three_heads_on_one_line_are_each_read(self):
        assert self._heads("IGST 18% 18000.00 CESS 12% 12000.00") == (
            ZERO,
            ZERO,
            Decimal("18000.00"),
            Decimal("12000.00"),
        )

    def test_a_spelt_out_rate_does_not_shift_the_column_after_it(self):
        # Each column is found at an offset measured on the line as printed,
        # and the rates come out of the line before the figures are read. Do
        # those in the wrong order and every column slides left by as much text
        # as the rates before it took up, while the offset goes on pointing
        # where the label used to be.
        #
        # "@ 6.00 %" is six characters of rate against "6%"'s two, so a line
        # that spells its rates out drifts far enough to matter — and this is
        # the ordinary way a tax invoice prints them.
        assert self._heads("CGST @ 6.00 % 1111.11 SGST @ 6.00 % 2222.22") == (
            Decimal("1111.11"),
            Decimal("2222.22"),
            ZERO,
            ZERO,
        )

    def test_the_drift_does_not_accumulate_into_the_last_figure(self):
        # The drift is the sum of every rate before the column, so the third
        # head on a line is where it first reaches all the way into a figure
        # rather than merely past a label.
        #
        # Landing *inside* "3,333.33" is the case worth pinning: the cut fell
        # after the "3," and the head read as ₹333.33 — an order of magnitude
        # of cess, off by a factor of ten rather than absent, on a line that
        # parses perfectly in every other respect. A missing figure is a blank
        # a reviewer can see; this one arrives looking like a figure.
        assert self._heads(
            "CGST @ 6.00 % 1,111.11 SGST @ 6.00 % 2,222.22 CESS @ 12.00 % 3,333.33"
        ) == (
            Decimal("1111.11"),
            Decimal("2222.22"),
            ZERO,
            Decimal("3333.33"),
        )

    def test_a_heading_row_with_no_figures_reads_nothing(self):
        # A table header naming both heads carries no amounts at all, so there
        # is nothing to attribute and nothing is invented.
        assert self._heads("Particulars      CGST      SGST") == (ZERO, ZERO, ZERO, ZERO)

    def test_a_combined_line_does_not_double_the_rate_either(self):
        # The rate is read per head from the first percentage on the line, and
        # an intra-state rate is reported as the sum of its two halves — so a
        # combined line offers one 18% and would be doubled to 36% by the same
        # reasoning that doubled the tax. 36 is not a slab, so `normalize_rate`
        # already refuses it; asserted here so that stays true if the slab list
        # ever grows.
        parsed = parse_heuristic(
            "TAX INVOICE\nTaxable Value: 100000.00\nCGST & SGST @ 18%: 18000.00\n"
        )
        assert parsed.tax_rate is None

    def test_the_rate_is_still_the_sum_of_both_halves_when_read_properly(self):
        # An 18% invoice prints as 9% + 9%. Reporting 9 would understate every
        # intra-state invoice by half, so the guard above must not have cost us
        # the ordinary case.
        parsed = parse_heuristic(
            "TAX INVOICE\nTaxable Value: 100000.00\n"
            "CGST @ 9%: 9000.00\nSGST @ 9%: 9000.00\n"
        )
        assert parsed.tax_rate == 18


class TestOneTaxHeadOnALineStillReadsAsBefore:
    """The single-head line is the ordinary case and must not have moved."""

    @staticmethod
    def _igst(text: str) -> Decimal:
        return parse_heuristic(f"TAX INVOICE\n{text}\n").igst

    def test_the_amount_after_the_label_is_taken(self):
        assert self._igst("IGST @ 18%: 81000.00") == Decimal("81000.00")

    def test_the_rate_is_not_mistaken_for_the_amount(self):
        assert self._igst("IGST @ 18% 81000.00") == Decimal("81000.00")

    def test_an_amount_printed_before_the_label_is_still_found(self):
        # A column layout can put the figure first. There is nothing after the
        # label to read, so the whole line is searched rather than giving up.
        assert self._igst("81000.00 IGST") == Decimal("81000.00")

    def test_the_last_figure_on_the_line_wins(self):
        # Invoices put the amount last, after the rate and any quantity.
        assert self._igst("IGST 18 % on 450000.00 = 81000.00") == Decimal("81000.00")


class TestALineThatOnlySaysTheWordIsNotATaxLine:
    """Naming a head is not declaring one, and the first reading of a head wins.

    Tax is read a line at a time, so any line carrying the letters ``CGST`` was
    treated as that head's line and the last number on it became the amount.
    The letters turn up in plenty of places that carry no tax at all — the rule
    46 footer every invoice prints, the page furniture of a multi-page one — and
    what the reader found there was a section number, a page count, or a piece
    of a date.

    The damage is not confined to the junk figure, because a head is only read
    once: page furniture near the top of the document is reached before the real
    tax block below it, so the true amount is discarded in favour of the page
    number rather than merely competing with it. That is the difference between
    a field that looks odd and an invoice whose tax is wrong on every screen
    that shows it.

    The figure must therefore be money-shaped — decimals, digit grouping, or
    both. A date, a section number and a page count are all bare integers, which
    is what makes the distinction hold on layouts nobody has seen yet.
    """

    REAL_TAX_BLOCK = "CGST @ 9% 9,000.00\nSGST @ 9% 9,000.00"

    @staticmethod
    def _heads(text: str) -> tuple:
        parsed = parse_heuristic(f"TAX INVOICE\nTaxable Value: 100000.00\n{text}\n")
        return parsed.cgst, parsed.sgst, parsed.igst, parsed.cess

    @pytest.mark.parametrize(
        "line",
        [
            # Rule 46(p) is printed on the face of essentially every invoice.
            "Note: IGST is not applicable on intra-state supply as per Section 8.",
            "Tax payable on reverse charge under IGST Section 9(3): 0",
            # Page furniture on a multi-page invoice.
            "Page 1 of 2 - CGST/SGST summary continued on 22/09/2024",
            # The heads named in a table's column headings, with no row under.
            "Rate    CGST    SGST    Total",
            # An identifier that happens to contain a head's letters.
            "Invoice No: IGST/9    Invoice Date: 05/05/2024",
        ],
    )
    def test_prose_and_page_furniture_declare_no_tax(self, line):
        assert self._heads(line) == (ZERO, ZERO, ZERO, ZERO)

    def test_a_footer_does_not_beat_the_tax_block_below_it(self):
        # The whole of the bug: read in document order, the footer's page number
        # and date were CGST and SGST, and the real block two lines down could
        # not correct them. Tax on this invoice read 2,026.00 of 18,000.00.
        cgst, sgst, igst, cess = self._heads(
            f"Page 1 of 2 - CGST/SGST summary continued on 22/09/2024\n{self.REAL_TAX_BLOCK}"
        )
        assert (cgst, sgst) == (Decimal("9000.00"), Decimal("9000.00"))
        assert (igst, cess) == (ZERO, ZERO)

    def test_a_section_number_is_not_an_igst_amount(self):
        # "Section 8" became ₹8 of IGST on an invoice that had none, which
        # `validate_period` then reports as an inter-state supply taxed as both.
        assert self._heads(
            f"{self.REAL_TAX_BLOCK}\nNote: IGST is not applicable as per Section 8."
        ) == (Decimal("9000.00"), Decimal("9000.00"), ZERO, ZERO)

    def test_a_combined_figure_survives_a_date_on_the_same_line(self):
        # The guard that leaves a combined line unread counts figures against
        # heads. Counting every number let the date make up the shortfall, so a
        # line with one amount and two heads looked like a line with a figure
        # each and handed the combined ₹18,000 to SGST alone.
        assert self._heads("Total Tax (CGST + SGST) 18,000.00 as on 22/09/2024") == (
            ZERO,
            ZERO,
            ZERO,
            ZERO,
        )

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("IGST @ 18%: 81000.00", Decimal("81000.00")),
            ("IGST @ 18% 81,000.00", Decimal("81000.00")),
            ("IGST 18,000", Decimal("18000")),
            ("81,000.00 IGST", Decimal("81000.00")),
        ],
    )
    def test_a_money_shaped_figure_is_still_read(self, line, expected):
        # Decimals or digit grouping, on either side of the label.
        assert self._heads(line)[2] == expected


class TestADateWrittenWithDotsIsNotAnAmount:
    """``22.09.2024`` is money-shaped for exactly as long as the pattern looks.

    Requiring a money shape is what stops a bare integer — a section number, a
    page count — being read as tax. A dotted date defeats that test rather than
    failing it: ``22.09`` is two digits, a point and two more, and nothing about
    those five characters says they are a day and a month. The reader stops
    there, because a third group belongs to no amount, and hands back the front
    of the date with the year left behind.

    So this is the same failure the shape test closed, arriving by the other
    date format — and the damaging half is unchanged. A head is read once, so a
    dotted date anywhere above the tax block takes the head and the real figure
    below it is discarded rather than preferred.

    DD.MM.YYYY is ordinary on an Indian invoice. The slash form never reached
    this code at all — ``22/09/2024`` carries no point and no grouping, so it is
    not money-shaped to begin with — which is precisely why the first pass at
    this missed it.
    """

    REAL_TAX_BLOCK = "IGST @ 18% 81,000.00"

    @staticmethod
    def _heads(text: str) -> tuple:
        parsed = parse_heuristic(f"TAX INVOICE\nTaxable Value: 450000.00\n{text}\n")
        return parsed.cgst, parsed.sgst, parsed.igst, parsed.cess

    @pytest.mark.parametrize(
        "line",
        [
            "Note: IGST is not applicable as per Section 8 dated 22.09.2024",
            "IGST reverse charge declaration signed 01.05.2024",
            # The year first, which is the other way round and matches the same.
            "IGST not applicable — see circular of 2024.09.22",
            # A day and month that need no padding still make five characters.
            "IGST not applicable as on 1.5.2024",
        ],
    )
    def test_a_dotted_date_declares_no_tax(self, line):
        assert self._heads(line) == (ZERO, ZERO, ZERO, ZERO)

    def test_a_dotted_date_does_not_beat_the_tax_block_below_it(self):
        # The whole of the bug: read in document order the date was the IGST,
        # and the real block below could not correct it. Tax on this invoice
        # read 22.09 of 81,000.00 — out by ₹80,977, with nothing to say so.
        assert self._heads(
            f"Note: IGST is not applicable as per Section 8 dated 22.09.2024\n"
            f"{self.REAL_TAX_BLOCK}"
        ) == (ZERO, ZERO, Decimal("81000.00"), ZERO)

    def test_a_dotted_date_cannot_make_up_a_combined_line_shortfall(self):
        # The guard that leaves a combined line unread counts figures against
        # heads. A dotted date supplies the missing figure by itself, so a line
        # with one amount and two heads looked like a line with a figure each
        # and handed the combined ₹18,000 to SGST alone.
        assert self._heads("Total Tax (CGST + SGST) 18,000.00 as on 22.09.2024") == (
            ZERO,
            ZERO,
            ZERO,
            ZERO,
        )

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # A real amount sharing the line with the date it was raised on.
            ("IGST @ 18% 81,000.00 dated 22.09.2024", Decimal("81000.00")),
            # And with the date first, where the amount is still the last figure.
            ("22.09.2024 IGST @ 18% 81,000.00", Decimal("81000.00")),
            # A point that joins nothing is an ordinary decimal.
            ("IGST @ 18% 81000.50", Decimal("81000.50")),
            # A point preceded by a letter is an abbreviation, not a separator.
            ("IGST Rs.81,000.00", Decimal("81000.00")),
        ],
    )
    def test_an_amount_beside_a_date_is_still_read(self, line, expected):
        assert self._heads(line)[2] == expected

    def test_both_heads_are_still_read_beside_a_dotted_date(self):
        # Two heads, a figure each, and a date that must count for neither.
        assert self._heads("CGST @ 9% 9,000.00 SGST @ 9% 9,000.00 on 22.09.2024") == (
            Decimal("9000.00"),
            Decimal("9000.00"),
            ZERO,
            ZERO,
        )


class TestAMinusSignIsNotPunctuation:
    """The separator before an amount and a negative sign are one character.

    ``Total - 5,000.00`` is printed, so the label patterns let a hyphen stand
    between the label and the figure. That is the same hyphen a negative amount
    begins with, and with nothing to tell them apart the separator ate the
    sign: ``Taxable Value -5,000.00`` handed back 5,000.00 — the figure with
    its sign removed rather than the figure.

    Of the three readings available, that one is the worst. ``-5,000`` is a
    credit note this product does not model, and shows as a negative on every
    screen. Nothing read is an empty box a reviewer can see. ``+5,000`` is an
    ordinary-looking invoice stating the opposite of the paper, and no step
    downstream re-derives it: booked as a supply it overstates turnover in
    GSTR-1, and on the purchase side it claims the credit the note was raised
    to take back.

    So an amount may not be preceded by a minus attached to it, and the two
    spellings part company on the space.
    """

    @staticmethod
    def _figures(line: str) -> tuple[Decimal, Decimal]:
        parsed = parse_heuristic(f"TAX INVOICE\n{line}\n")
        return parsed.taxable_value, parsed.total_value

    @pytest.mark.parametrize(
        "line",
        [
            "Taxable Value -5,000.00",
            "Taxable Amount -5,000.00",
            "Sub-Total -5,000.00",
            "Net Amount -5,000.00",
            "Grand Total -5,000.00",
            "Total Value -5,000.00",
            "Amount Payable -5,000.00",
            "Invoice Total -5,000.00",
            # A currency marker between the label and the sign does not
            # detach it: the minus is still the character before the figure.
            "Taxable Value: Rs. -5,000.00",
            "Grand Total ₹-5,000.00",
        ],
    )
    def test_an_attached_minus_leaves_the_field_empty(self, line):
        # Empty rather than positive, which is this module's standing trade
        # everywhere else: a blank a reviewer can see beats a plausible wrong
        # figure nobody re-checks.
        assert self._figures(line) == (ZERO, ZERO)

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # The reason the hyphen is allowed at all — unchanged.
            ("Taxable Value - 5,000.00", (Decimal("5000.00"), ZERO)),
            ("Grand Total - 5,000.00", (ZERO, Decimal("5000.00"))),
            # And the ordinary separators, which never involved a hyphen.
            ("Taxable Value: 5,000.00", (Decimal("5000.00"), ZERO)),
            ("Grand Total 5,000.00", (ZERO, Decimal("5000.00"))),
            ("Net Amount Rs. 5,000.00", (Decimal("5000.00"), ZERO)),
            # The label's own hyphen is not the separator and never was.
            ("Sub-Total 5,000.00", (Decimal("5000.00"), ZERO)),
        ],
    )
    def test_a_hyphen_that_is_a_separator_still_reads_the_amount(self, line, expected):
        assert self._figures(line) == expected

    def test_the_space_is_the_whole_difference(self):
        # Same eight characters of label, same figure, one space apart — and
        # the pair is what the fix is: one is a separator, one is a sign.
        assert self._figures("Grand Total - 5,000.00") == (ZERO, Decimal("5000.00"))
        assert self._figures("Grand Total -5,000.00") == (ZERO, ZERO)


class TestANegativeAmountNeverReachesTheRow:
    """Extraction is the one door into this product that would take a negative.

    Every other door refuses it: ``InvoiceUpdate`` carries ``ge=0`` on all six
    money fields, and a GSTR-2B states a credit note as positive figures with
    the sign carried by ``document_type`` rather than by the money. But
    ``apply_parsed`` writes what the extractors produced straight onto the row,
    past all of that — so a tax line reading ``IGST @ 18% -9,000.00`` stored
    igst = -9000.00 and the dashboard reported input tax credit of *minus* nine
    thousand rupees, with nothing on the invoice to say so.

    Both extractors reach it by ordinary means, which is why the guard sits in
    ``validate`` where the two paths meet rather than in either one of them.

    Zeroed rather than kept, because a credit note is not a thing this product
    models: with no document type to carry the sign, a negative row is not a
    credit note that got in, it is an invoice whose figures are wrong.
    """

    FIELDS = ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value")

    @pytest.mark.parametrize("attr", FIELDS)
    def test_a_negative_is_zeroed_and_named(self, attr):
        parsed = ParsedInvoice()
        setattr(parsed, attr, Decimal("-9000.00"))
        validate(parsed)

        assert getattr(parsed, attr) == ZERO
        assert f"Discarded a negative {attr.replace('_', ' ')}: -9000.00" in parsed.warnings

    def test_a_positive_amount_is_left_alone(self):
        parsed = validate(ParsedInvoice(taxable_value=Decimal("50000.00"), igst=Decimal("9000.00")))

        assert parsed.taxable_value == Decimal("50000.00")
        assert parsed.igst == Decimal("9000.00")
        assert not any(w.startswith("Discarded a negative") for w in parsed.warnings)

    def test_the_heuristic_path_cannot_store_a_negative_tax(self):
        # The tax-line reader takes its sign from _MONEY_FIGURE, which begins
        # "-?" — a discount summarised under a tax head is enough to produce
        # one. Read before validate, this is -9000.00.
        raw = parse_heuristic("TAX INVOICE\nTaxable Value: 50,000.00\nIGST @ 18% -9,000.00\n")
        assert raw.igst == Decimal("-9000.00")

        assert validate(raw).igst == ZERO

    def test_the_model_path_cannot_store_a_negative_tax(self):
        # to_money bounds a model's magnitude but not its sign, so a payload
        # saying -9000 arrives verbatim.
        raw = _from_model_payload({"igst": -9000, "taxable_value": -50000}, "", "m")
        assert (raw.igst, raw.taxable_value) == (Decimal("-9000"), Decimal("-50000"))

        parsed = validate(raw)
        assert (parsed.igst, parsed.taxable_value) == (ZERO, ZERO)

    def test_the_clamp_runs_before_the_footing_check(self):
        # Ordering, which is the reason the loop is at the top of validate:
        # the total reported as not footing has to be stated against the
        # figures actually stored, not the ones that were thrown away.
        parsed = validate(
            ParsedInvoice(
                taxable_value=Decimal("50000.00"),
                igst=Decimal("-9000.00"),
                total_value=Decimal("41000.00"),
            )
        )
        assert "Total 41000.00 does not equal taxable value + tax (50000.00)" in parsed.warnings

    def test_a_discarded_negative_costs_confidence(self):
        # What routes the document to a reviewer: the warning is worth 0.1 of
        # confidence, the same as every other unresolved inconsistency.
        parsed = ParsedInvoice(igst=Decimal("-9000.00"))
        parsed.confidence = 0.9
        parsed.supplier_gstin, parsed.invoice_number = SUPPLIER_GSTIN_SAME_STATE, "X/1"
        parsed.invoice_date = date(2026, 5, 2)

        assert validate(parsed).confidence == 0.8

    def test_a_whole_invoice_with_a_negative_tax_line_is_kept_and_flagged(self):
        # End to end, because the promise is that the invoice still arrives:
        # a flagged invoice can be corrected, a rejected one is retyped from
        # paper.
        parsed = parse_invoice(
            text=(
                f"TAX INVOICE\nGSTIN: {SUPPLIER_GSTIN_SAME_STATE}\n"
                "Invoice No: MH/2026/119\nInvoice Date: 02/05/2026\n"
                "Taxable Value: 50,000.00\nIGST @ 18% -9,000.00\n"
                "Grand Total: 41,000.00\n"
            )
        )

        assert parsed.invoice_number == "MH/2026/119"
        assert parsed.igst == ZERO
        assert "Discarded a negative igst: -9000.00" in parsed.warnings


class TestAccountingNegativesAreNegatives:
    """P34 M2: only "-9,000.00" was recognised as negative.

    Accounting exports write a negative as "(9,000.00)" and Tally prints one
    as "9,000.00-". Both were read as +9,000: the guard above never saw them,
    so a credit note in either notation was stored as a positive invoice —
    output tax on a sale that was reversed, input credit on a purchase that
    was returned — with no warning and no loss of confidence to send it to a
    reviewer. They are negatives now, and the guard zeroes and names them.
    """

    @pytest.mark.parametrize("figure", ["(9,000.00)", "9,000.00-", "( 9,000.00 )"])
    def test_the_model_path_reads_the_sign(self, figure):
        assert to_money(figure) == Decimal("-9000.00")

    @pytest.mark.parametrize("figure", ["9,000.00", "Rs. 9,000.00", "₹ 9,000.00"])
    def test_an_ordinary_amount_is_unchanged(self, figure):
        assert to_money(figure) == Decimal("9000.00")

    @pytest.mark.parametrize(
        "line", ["IGST @ 18% (9,000.00)", "IGST @ 18% 9,000.00-"]
    )
    def test_the_heuristic_tax_line_reads_the_sign(self, line):
        raw = parse_heuristic(f"TAX INVOICE\nTaxable Value: 50,000.00\n{line}\n")
        assert raw.igst == Decimal("-9000.00")

    @pytest.mark.parametrize("figure", ["(50,000.00)", "50,000.00-"])
    def test_the_heuristic_labelled_amount_reads_the_sign(self, figure):
        raw = parse_heuristic(f"TAX INVOICE\nTaxable Value: {figure}\n")
        assert raw.taxable_value == Decimal("-50000.00")

    def test_a_tally_credit_note_is_flagged_not_filed(self):
        parsed = parse_invoice(
            text=(
                f"CREDIT NOTE\nGSTIN: {SUPPLIER_GSTIN_SAME_STATE}\n"
                "Invoice No: CN/2026/7\nInvoice Date: 02/05/2026\n"
                "Taxable Value: 50,000.00-\nIGST @ 18% 9,000.00-\n"
                "Grand Total: 59,000.00-\n"
            )
        )

        assert (parsed.taxable_value, parsed.igst, parsed.total_value) == (ZERO, ZERO, ZERO)
        assert "Discarded a negative igst: -9000.00" in parsed.warnings

    def test_a_hyphen_between_label_and_amount_is_still_punctuation(self):
        # "Total - 5,000.00" reads as before; only a minus *on* the figure counts.
        raw = parse_heuristic("TAX INVOICE\nTaxable Value - 5,000.00\n")
        assert raw.taxable_value == Decimal("5000.00")


class TestAPartlyReadAmountIsNotStored:
    """The ₹1,000 invoice that stored one rupee.

    ``_AMOUNT`` spells a well-formed figure and stops at the first character
    that is not part of one, and stopping is not failing: what it hands back is
    the *front* of the figure rather than nothing. OCR supplies the broken
    middles constantly — a zero read as the letter O, a thousands comma read as
    a space — and ``to_money`` is asked only whether the digits in hand are an
    amount, never whether they are the whole amount.

    Taxable value and total are the two fields the footing check in ``validate``
    is made *of*, and it only runs when both are non-zero. So a document
    printing a grand total and no taxable line — most receipts — stored ₹1,
    raised nothing, lost no confidence, and showed one rupee on every screen.
    """

    def _parse(self, line):
        return parse_heuristic(f"TAX INVOICE\n{line}\n")

    # The two shapes OCR actually produces, on both of the fields.
    @pytest.mark.parametrize(
        ("label", "attr"),
        [("Grand Total", "total_value"), ("Taxable Value", "taxable_value")],
    )
    @pytest.mark.parametrize("figure", ["1,OOO.00", "1 000.00", "1O,000.00"])
    def test_a_broken_grouping_is_refused_rather_than_truncated(self, label, attr, figure):
        parsed = self._parse(f"{label}: {figure}")

        assert getattr(parsed, attr) == ZERO
        assert f"Discarded a partly-read {attr.replace('_', ' ')}: {figure}" in parsed.warnings

    def test_the_rupee_is_the_whole_point(self):
        # Named on its own because the number is the bug: not a wrong figure a
        # reviewer would query, a plausible small one they would not.
        assert self._parse("Grand Total: 1,OOO.00").total_value != Decimal("1")
        assert self._parse("Grand Total: 1 000.00").total_value != Decimal("1")

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            # Whole figures, which are the overwhelming majority and must be
            # untouched by the guard.
            ("Grand Total: 118000.00", Decimal("118000.00")),
            ("Grand Total: 1,18,000.00", Decimal("118000.00")),  # Indian grouping
            ("Grand Total: 5,000", Decimal("5000")),
            ("Grand Total: 118000", Decimal("118000")),
            ("Grand Total Rs. 118000.00", Decimal("118000.00")),
            ("Grand Total: 5000 INR", Decimal("5000")),
            ("Invoice Total 45,000.00 as on 22/09/2024", Decimal("45000.00")),
        ],
    )
    def test_a_figure_read_whole_is_stored_and_not_warned_about(self, line, expected):
        parsed = self._parse(line)

        assert parsed.total_value == expected
        assert not [w for w in parsed.warnings if w.startswith("Discarded a partly-read")]

    @pytest.mark.parametrize(
        "next_line",
        [
            "18% GST included",  # a rate
            "22/09/2024",  # a footer date
            "30 days credit",  # payment terms
            "24 Nos",  # a quantity column
        ],
    )
    def test_the_line_below_is_not_this_figure_s_missing_thousands(self, next_line):
        """The guard's own failure mode, which is the expensive one.

        "A space and two or three digits" is far commoner as the next thing
        printed than as the rest of this figure, so read loosely the guard
        discarded whole, correctly-read totals on documents much commoner than
        the ones it rescues — this bug, caused by its own fix.
        """
        parsed = self._parse(f"Grand Total: 100000\n{next_line}")

        assert parsed.total_value == Decimal("100000")
        assert not [w for w in parsed.warnings if w.startswith("Discarded a partly-read")]

    def test_a_second_column_on_the_same_line_is_not_the_missing_thousands_either(self):
        parsed = self._parse("Grand Total: 5000  25 items")

        assert parsed.total_value == Decimal("5000")

    def test_the_warning_quotes_what_the_page_actually_held(self):
        # An empty box beats a wrong one only when someone can tell it was
        # emptied on purpose, so the discarded text is named.
        parsed = self._parse("Grand Total: 1,OOO.00")

        assert parsed.warnings == ["Discarded a partly-read total value: 1,OOO.00"]

    def test_a_missing_label_is_still_silent(self):
        # No match at all is not a discard: an invoice that never printed a
        # taxable line has nothing to warn about.
        parsed = self._parse("Grand Total: 118000.00")

        assert parsed.taxable_value == ZERO
        assert parsed.warnings == []

    def test_the_discard_costs_confidence_and_routes_to_review(self):
        # What the silent version cost: the ₹1 kept its field non-empty, so
        # coverage counted it as found and the warning that would have lowered
        # confidence was never raised.
        good = parse_invoice(text=INTRASTATE_INVOICE)
        broken = parse_invoice(text=INTRASTATE_INVOICE.replace("118000.00", "1 18 000.00"))

        assert broken.total_value == ZERO
        assert broken.confidence < good.confidence

    def test_the_invoice_still_arrives(self):
        # End to end: a flagged invoice can be corrected, a rejected one is
        # retyped from paper.
        parsed = parse_invoice(text=INTRASTATE_INVOICE.replace("118000.00", "1,18,OOO.00"))

        assert parsed.invoice_number == "MH/2026/118"
        assert parsed.supplier_gstin == SUPPLIER_GSTIN_SAME_STATE
        assert parsed.taxable_value == Decimal("100000.00")
        assert "Discarded a partly-read total value: 1,18,OOO.00" in parsed.warnings


class TestAMonthFirstDateIsReadRatherThanRefused:
    """Preferring day-first is not the same as refusing month-first.

    Every format tried was day-first, so ``12/31/2024`` matched none of them and
    the invoice came back with no date at all. That is the more expensive of the
    two readings: a date read a month out files the invoice in the neighbouring
    return, a date not read at all takes it out of *every* return — off the
    register, off the dashboard, out of the GSTR-1, with nothing downstream left
    to notice.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("12/31/2024", date(2024, 12, 31)),
            ("12-31-2024", date(2024, 12, 31)),
            ("12.31.2024", date(2024, 12, 31)),
            ("Jan 5, 2026", date(2026, 1, 5)),
            ("January 5 2026", date(2026, 1, 5)),
        ],
    )
    def test_a_date_with_only_one_reading_gets_it(self, raw, expected):
        assert to_date(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("03/04/2026", date(2026, 4, 3)),
            ("01/02/2026", date(2026, 2, 1)),
            ("05-06-2026", date(2026, 6, 5)),
            ("01/02/26", date(2026, 2, 1)),
        ],
    )
    def test_an_ambiguous_date_is_still_read_day_first(self, raw, expected):
        """The fallback costs nothing in ambiguity.

        A two-part numeric date only reaches month-first when the day-first
        reading was *invalid*, and a first field above 12 means it was never a
        month. These all match in the first pass and never reach it.
        """
        assert to_date(raw) == expected

    def test_a_two_digit_year_is_not_read_as_the_year_24(self):
        # "%d-%m-%Y" is tried before "%d-%m-%y" and "%m/%d/%Y" before
        # "%m/%d/%y", so the ordering has to not let %Y swallow a two-digit
        # year — a date in the year 24 AD fails the plausibility check below
        # and leaves the invoice with no date at all.
        assert to_date("31-12-24") == date(2024, 12, 31)
        assert to_date("12/31/24") == date(2024, 12, 31)

    def test_nonsense_in_either_order_is_still_refused(self):
        assert to_date("13/13/2024") is None
        assert to_date("00/00/0000") is None
        assert to_date("nonsense") is None

    def test_the_invoice_reaches_a_filing_period(self):
        # Why the field matters: it alone decides which return the invoice
        # appears in, and an invoice in no period leaves every screen at once.
        parsed = parse_invoice(text=INTRASTATE_INVOICE.replace("02/05/2026", "12/31/2024"))

        assert parsed.invoice_date == date(2024, 12, 31)


class TestANumberQuotedFromAnotherDocumentIsNotThisOne:
    """A cited invoice number is somebody else's, and it was taken as this one.

    Documents quote each other constantly: a credit note has to name the
    original invoice to be valid under rule 53, and an invoice for continuing
    work opens "Against our Invoice No: ...". Both print the older number
    *above* the document's own, and the leftmost match won.

    That is worse than reading nothing. The value is not noise — it is a real
    number belonging to a real earlier document, so reconciliation matches it to
    that document's GSTR-2B row, duplicate detection sees the earlier invoice
    already filed under it, and GSTR-1 files two supplies under one ``inum``.
    Nothing downstream has a reason to look twice.
    """

    @pytest.mark.parametrize(
        "reference",
        [
            "Against our Invoice No: OLD-100",
            "Against Invoice No. OLD-100",
            "Ref: Invoice No 1001",
            "Reference Invoice No: OLD-100",
            "With reference to your Invoice No: OLD-100",
            "Referring to our Invoice No. OLD-100",
            "Original Invoice No: OLD-100",
            "Orig. Invoice No: OLD-100",
            "Previous Invoice No: OLD-100",
            "Prev Invoice No 1001",
            "vide Invoice No 1001",
            "w.r.t. Invoice No. OLD-100",
            "wrt Invoice No OLD-100",
        ],
    )
    def test_the_document_s_own_number_is_read_past_the_one_it_cites(self, reference):
        text = f"CREDIT NOTE\n{reference}\nInvoice No: MINE-205\nGrand Total: 1,180.00\n"

        assert parse_heuristic(text).invoice_number == "MINE-205"

    def test_a_cited_number_is_dropped_rather_than_stored_when_it_is_the_only_one(self):
        # The choice the module makes everywhere else: an empty field a reviewer
        # can see beats a plausible number belonging to something else.
        text = "CREDIT NOTE\nAgainst our Invoice No: OLD-100\nGrand Total: 1,180.00\n"

        assert parse_heuristic(text).invoice_number is None

    def test_the_empty_field_is_said_out_loud(self):
        # What makes the blank a reviewable state rather than a quiet loss.
        text = "CREDIT NOTE\nAgainst our Invoice No: OLD-100\nGrand Total: 1,180.00\n"

        parsed = parse_invoice(text=text)

        assert parsed.invoice_number is None
        assert any("invoice number" in warning.lower() for warning in parsed.warnings)

    def test_the_reference_word_has_to_be_next_to_the_label(self):
        # Every Indian invoice is printed in triplicate and says so. Read
        # "ORIGINAL" anywhere on the line as a reference to an original
        # *invoice* and the number comes off every document laid out this way.
        text = "ORIGINAL FOR RECIPIENT    Invoice No: MINE-41\n"

        assert parse_heuristic(text).invoice_number == "MINE-41"

    def test_a_reference_on_the_line_above_does_not_reach_down_to_this_one(self):
        text = "Against our Invoice No.\nInvoice No: MINE-41\n"

        assert parse_heuristic(text).invoice_number == "MINE-41"

    def test_a_revised_invoice_keeps_its_own_number(self):
        # Rule 53(1) heads the document "Revised Invoice" and gives it its own
        # serial; the document it replaces is named separately as the original.
        # So "Revised" introduces the number being read, not a citation.
        text = "REVISED INVOICE\nOriginal Invoice No: OLD-1\nRevised Invoice No: R-9\n"

        assert parse_heuristic(text).invoice_number == "R-9"

    def test_an_ordinary_invoice_with_nothing_to_cite_is_untouched(self):
        assert parse_heuristic(INTRASTATE_INVOICE).invoice_number == "MH/2026/118"

    def test_the_wrong_number_would_have_reached_the_stored_invoice(self):
        # Why it matters at all: the field is not cosmetic, it is what the
        # register, reconciliation and duplicate detection all key on.
        text = INTRASTATE_INVOICE.replace(
            "Invoice No: MH/2026/118",
            "Against our Invoice No: MH/2025/004\nInvoice No: MH/2026/118",
        )

        assert parse_invoice(text=text).invoice_number == "MH/2026/118"


class TestTheEWayBillNumberIsNotTheInvoiceNumber:
    """The consignment's number is printed above the invoice's, and won.

    An e-way bill is required for most consignments over ₹50,000 and its number
    is printed at the top of the invoice it travels with, in the same block as
    the IRN. "Bill" is one of the labels the number pattern reads and nothing
    in it looked at what came before, so the invoice was stored under a
    transport document's number.

    Twelve digits are as plausible as any serial, so nothing downstream
    objects: GSTR-1 files the supply under it, the supplier's real GSTR-2B row
    matches nothing, and duplicate detection keys on a value that changes with
    every consignment.
    """

    @pytest.mark.parametrize(
        "spelling",
        [
            "E-Way Bill No: 123456789012",
            "E Way Bill No: 123456789012",
            "EWay Bill No. 123456789012",
            "Way Bill No 123456789012",
            "Waybill No: 123456789012",
        ],
    )
    def test_the_invoice_s_own_number_is_read_past_it(self, spelling):
        text = f"{spelling}\nInvoice No: MH/2026/118\nGrand Total: 59,000.00\n"

        assert parse_heuristic(text).invoice_number == "MH/2026/118"

    def test_a_consignment_number_alone_is_not_promoted_to_the_invoice(self):
        text = "E-Way Bill No: 123456789012\nGrand Total: 59,000.00\n"

        assert parse_heuristic(text).invoice_number is None

    def test_a_bill_of_supply_still_carries_its_own_number(self):
        # Rule 49: a composition dealer issues these and nothing else, so a
        # pattern that cannot read one leaves every document they send unnumbered.
        assert parse_heuristic("Bill of Supply No: 5\n").invoice_number == "5"
        assert parse_heuristic("Bill of Supply No.: BOS/26/9\n").invoice_number == "BOS/26/9"

    def test_a_plain_bill_number_is_unchanged(self):
        assert parse_heuristic("Bill No. 42\n").invoice_number == "42"


class TestALabelWithNothingBesideItReadsNoNumber:
    """The separator ran past the end of the line and took the next word.

    A document does not always print the value beside the label. A tabular
    layout heads its columns and puts the values on the row below; a wrapped
    line leaves the label alone at the end of one. The separator between label
    and value was any run of whitespace, and whitespace includes the line break,
    so the pattern carried on to the next line and returned the first word it
    found there.

    What came back was never nothing — it was "Date", "Bill", "Total", "of":
    strings that look like data in the one field nothing downstream can check.
    It files into GSTR-1 as ``inum``, reconciliation matches a GSTR-2B row on
    it, and duplicate detection keys on it.
    """

    @pytest.mark.parametrize(
        ("text", "was"),
        [
            ("Invoice No.\nDate: 02/05/2026\n", "Date"),
            ("Invoice No :\nBill To: ACME TRADERS\n", "Bill"),
            ("Bill No.\nTotal: 500.00\n", "Total"),
            ("TAX INVOICE\nNo. of Packages: 12\n", "of"),
            ("Tax Invoice No\nDated 02/05/2026\n", "Dated"),
        ],
    )
    def test_the_word_on_the_next_line_is_not_this_document_s_number(self, text, was):
        parsed = parse_heuristic(text)

        assert parsed.invoice_number != was
        assert parsed.invoice_number is None

    def test_a_column_heading_does_not_hand_back_the_heading_beside_it(self):
        # Same failure without a line break in it: the value position holds the
        # next column's label, and the value row is nowhere near it.
        text = "Invoice No.   Invoice Date\nMH/2026/118   02/05/2026\n"

        assert parse_heuristic(text).invoice_number is None

    @pytest.mark.parametrize(
        "placeholder",
        ["Invoice No: NA\n", "Invoice No: TBD\n", "Invoice No: None\n"],
    )
    def test_a_word_with_no_digit_in_it_is_not_a_serial(self, placeholder):
        # Rule 46(b) makes the number a consecutive serial, and a placeholder
        # is not one — it would key duplicate detection for every document the
        # supplier ever sends with the box left unfilled.
        assert parse_heuristic(placeholder).invoice_number is None

    def test_one_letter_after_a_confirmed_label_is_still_a_number(self):
        # A first-year series. It reaches here only through the branch that
        # saw a "No" token, which a column heading's neighbour does not.
        assert parse_heuristic("Invoice No.: A\n").invoice_number == "A"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Invoice No: MH/2026/118", "MH/2026/118"),
            ("Invoice No.: INV-001", "INV-001"),
            ("Invoice No :- 5", "5"),
            ("Bill No. 42", "42"),
            ("Tax Invoice No: CD/99", "CD/99"),
            ("Invoice #A-9", "A-9"),
            ("Invoice No\tMH-3", "MH-3"),
            ("Invoice No.: MH-1", "MH-1"),
        ],
    )
    def test_a_value_printed_beside_its_label_is_read_as_before(self, line, expected):
        # Including the non-breaking space a PDF extractor emits, which is why
        # the restriction is "not a line break" rather than "a space or a tab".
        assert parse_heuristic(f"{line}\n").invoice_number == expected

    def test_the_document_below_a_lone_label_is_still_read(self):
        # The label with nothing beside it must not take the real number out of
        # the rest of the page either.
        text = "Invoice No.\nDate: 02/05/2026\nInvoice No: MH-7\n"

        assert parse_heuristic(text).invoice_number == "MH-7"

    def test_the_whole_invoice_is_unaffected(self):
        assert parse_heuristic(INTRASTATE_INVOICE).invoice_number == "MH/2026/118"

    def test_the_reviewer_is_told_the_number_is_missing(self):
        # The trade this makes only holds if the blank is visible: nothing is
        # gained by refusing "Date" and then filing the invoice silently.
        parsed = parse_invoice(text="Invoice No.\nDate: 02/05/2026\nGrand Total: 500.00\n")

        assert parsed.invoice_number is None
        assert any("invoice number" in warning.lower() for warning in parsed.warnings)


class TestRCMIsTheSameQuestionAsReverseCharge:
    """The acronym is often the only wording on the page, and it read as "no".

    Rule 46(p) requires the answer on the face of every tax invoice, but not the
    words: pre-printed forms have a box to fit, so "Tax payable under RCM: Yes"
    is as common as the phrase spelt out. None of those contained "reverse
    charge", so they matched nothing and fell to the field's default — ``False``,
    indistinguishable from an invoice that says the answer is no.

    A missed yes is the expensive direction. The invoice is then marked
    creditable (``itc_eligible and not reverse_charge``) and the business claims
    credit for tax it never paid and still owes; on a sale it prints
    ``rchrg: "N"`` into the customer's GSTR-2B, so both parties drop the same
    liability at once.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "Tax payable under RCM: Yes",
            "RCM Applicable: Yes",
            "RCM Applicable - Y",
            "Whether tax is payable under RCM (Y/N): Y",
            "RCM: Y",
            "Whether GST is payable under reverse charge (RCM): Yes",
            "Reverse Charge (RCM): Yes",
            "Reverse Charge Mechanism (RCM) Applicable: Yes",
            "Is Reverse Charge Mechanism (RCM) applicable: Yes",
            "Reverse Charge Mechanism: Yes",
        ],
    )
    def test_an_answer_of_yes_flags_the_invoice_however_it_is_spelt(self, line):
        assert parse_heuristic(f"Invoice No: A-1\n{line}\n").reverse_charge is True

    @pytest.mark.parametrize(
        "line",
        [
            "Tax payable under RCM: No",
            "RCM Applicable: No",
            "Whether tax is payable under RCM (Y/N): N",
            "RCM: Not Applicable",
            "Whether GST is payable under reverse charge (RCM): No",
            "Reverse Charge Mechanism (RCM) Applicable: No",
            "Reverse Charge Mechanism: No",
        ],
    )
    def test_an_answer_of_no_still_leaves_the_invoice_ordinary(self, line):
        assert parse_heuristic(f"Invoice No: A-1\n{line}\n").reverse_charge is False

    @pytest.mark.parametrize(
        "line",
        [
            "RCM ENTERPRISES PRIVATE LIMITED",
            "Sold By: RCM Yarn Traders",
            "Bank: RCM Co-operative Bank, Latur",
        ],
    )
    def test_the_letters_in_a_trade_name_declare_nothing(self, line):
        # The acronym cannot fire on its own: what follows a name is more name,
        # which is not an answer, and a label with no answer matches nothing.
        assert parse_heuristic(f"{line}\nInvoice No: A-1\n").reverse_charge is False

    def test_the_phrase_spelt_out_is_unchanged(self):
        assert parse_heuristic("Reverse Charge (Y/N): Y\n").reverse_charge is True
        assert parse_heuristic("Whether Reverse Charge Applicable: No\n").reverse_charge is False

    def test_an_invoice_that_says_nothing_is_still_ordinary(self):
        assert parse_heuristic(INTRASTATE_INVOICE).reverse_charge is False

    def test_the_flag_reaches_the_stored_invoice(self):
        # Why the field matters: it is what takes the invoice's tax out of the
        # credit pool and puts it into 3.1(d) as a liability to settle in cash.
        text = INTRASTATE_INVOICE.replace(
            "TAX INVOICE", "TAX INVOICE\nWhether tax is payable under RCM (Y/N): Y"
        )

        assert parse_invoice(text=text).reverse_charge is True


class TestOneHeadingOverBothTheNumberAndTheDate:
    """"Invoice No. & Date : INV-42 dt. 15/04/2026" — one label, two fields.

    Most tabular Indian templates head that band once rather than twice, and
    until this was read the document came back with neither field. The number
    is the worse-looking half — a return needs an ``inum`` for every B2B line —
    but the date is the expensive one: it decides the period, so an invoice
    that loses it is one nothing files in any month, and it is missing from the
    register, the dashboard and the GSTR-1 together.

    The joined heading is ranked with the explicit ``Invoice Date`` label
    rather than below the loose one, because it names the invoice's own date
    just as plainly. What that buys is the due-date case: a due date is
    normally printed above the invoice's own and would otherwise win on being
    leftmost.
    """

    HEAD = "NORTHWIND SUPPLIES\nGSTIN: 29AABCU9603R1ZM\nTAX INVOICE\n"

    @pytest.mark.parametrize(
        "line",
        [
            "Invoice No. & Date : INV-2026-0042 dt. 15/04/2026",
            "Invoice No & Date: INV-2026-0042 / 15-04-2026",
            "Invoice No. and Date : INV-2026-0042 dated 15/04/2026",
            "Tax Invoice No & Dt.: INV-2026-0042 dt. 15/04/2026",
            "Bill No & Date - INV-2026-0042 dt 15.04.2026",
        ],
    )
    def test_both_fields_are_read_however_the_pair_is_punctuated(self, line):
        parsed = parse_heuristic(f"{self.HEAD}{line}\n")

        assert parsed.invoice_number == "INV-2026-0042"
        assert parsed.invoice_date == date(2026, 4, 15)

    def test_a_separate_label_for_each_field_is_unchanged(self):
        parsed = parse_heuristic(
            f"{self.HEAD}Invoice No: INV-2026-0042\nInvoice Date: 15/04/2026\n"
        )

        assert parsed.invoice_number == "INV-2026-0042"
        assert parsed.invoice_date == date(2026, 4, 15)

    def test_a_due_date_above_the_heading_does_not_become_the_invoice_date(self):
        parsed = parse_heuristic(
            f"{self.HEAD}Due Date: 30/06/2026\n"
            "Invoice No. & Date : INV-2026-0042 dt. 15/04/2026\n"
        )

        assert parsed.invoice_date == date(2026, 4, 15)

    def test_a_cited_original_in_the_same_shape_is_still_passed_over(self):
        """Rule 53 makes a note carry the original's number and date."""
        parsed = parse_heuristic(
            f"{self.HEAD}Original Invoice No. & Date : OLD-9 dt. 02/01/2026\n"
            "Invoice No. & Date : INV-2026-0042 dt. 15/04/2026\n"
        )

        assert parsed.invoice_number == "INV-2026-0042"
        assert parsed.invoice_date == date(2026, 4, 15)

    def test_an_e_way_bill_in_the_same_shape_is_still_passed_over(self):
        parsed = parse_heuristic(
            f"{self.HEAD}E-Way Bill No & Date: 123456789012 dt. 14/04/2026\n"
            "Invoice No. & Date : INV-2026-0042 dt. 15/04/2026\n"
        )

        assert parsed.invoice_number == "INV-2026-0042"
        assert parsed.invoice_date == date(2026, 4, 15)

    def test_the_heading_alone_over_an_empty_band_reads_nothing(self):
        """A column head with its values on the next line, as before.

        The same answer the tabular layouts already get: the value has to be
        beside the label, and an empty field a reviewer can see beats a
        heading word stored as a number.
        """
        parsed = parse_heuristic(f"{self.HEAD}Invoice No. & Date\nINV-2026-0042   15/04/2026\n")

        assert parsed.invoice_number is None
        assert parsed.invoice_date is None

    def test_the_conjunction_alone_does_not_let_the_value_be_skipped(self):
        """Only a joined *heading* is absorbed, not any "&" before the value.

        Otherwise the pattern would step over whatever an invoice prints
        between the label and its value and read the next token as the number.
        """
        parsed = parse_heuristic(f"{self.HEAD}Invoice No. & OLD-9 INV-2026-0042\n")

        assert parsed.invoice_number != "INV-2026-0042"
