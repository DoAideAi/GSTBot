"""Turn an uploaded invoice into the structured fields GST filing needs.

Two extractors, tried in order:

1. **The model.** An OpenRouter free model reads the invoice text — or the
   image itself, via a free vision model — and returns JSON.
2. **Heuristics.** Regexes for the fields that have a fixed shape on an Indian
   tax invoice: the GSTIN (checksummed, so a hit is almost never a false one),
   the invoice number, the date, the tax amounts.

The heuristic pass is not only a fallback. It runs *after* a successful model
call too, to fill fields the model left blank and to overrule a GSTIN it
hallucinated — a 15-character string either passes the mod-36 check digit or
it does not, and that is a stronger signal than the model's confidence. What
comes back is a :class:`ParsedInvoice` with a confidence the caller can route
on, never an exception: a free-tier rate limit must not lose someone's invoice.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.core.config import settings
from app.models.mixins import MONEY_MAX
from app.services import document_text, gst_calendar
from app.services import gstin as gstin_service
from app.services import hsn as hsn_service
from app.services.openrouter_client import OpenRouterError, chat_json, image_data_url, is_configured

logger = logging.getLogger(__name__)

# The rates GST actually levies, and the one definition of them. An extracted
# rate outside this set is a misread — most often a total mistaken for a
# percentage — and there is no 15% or 20% slab to be generous about.
#
# This module owns the list because it is the lowest one that needs it, and
# ``app.services.filing`` imports it rather than keeping a second copy. It had
# a second copy, and the two disagreed: filing knew about 0.1%, 1%, 1.5%, 6%
# and 7.5% and the parser did not, so every invoice on one of those slabs had
# its rate discarded here as impossible and reached filing with nothing in the
# field. That is not a cosmetic loss — filing's "tax does not match rate x
# taxable value" check is skipped when there is no rate to apply, so precisely
# the invoices whose rate the product could not read were also the ones whose
# arithmetic it never verified.
#
# 1.5% is the affordable-housing rate and 0.1% is the merchant-export one;
# both are printed on real invoices, halved into CGST and SGST, and both now
# survive the round trip.
VALID_TAX_RATES = (
    Decimal("0"),
    Decimal("0.1"),
    Decimal("0.25"),
    Decimal("1"),
    Decimal("1.5"),
    Decimal("3"),
    Decimal("5"),
    Decimal("6"),
    Decimal("7.5"),
    Decimal("12"),
    Decimal("18"),
    Decimal("28"),
    Decimal("40"),
)

# A number with optional Indian digit grouping and up to two decimals.
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d{1,2})?")

# The same, narrowed to figures an invoice prints as *money*: a decimal part, or
# digit grouping, or both. A bare run of digits is not one.
#
# This is what tells a tax line from a line that merely says the word. Tax is
# read a line at a time (see :func:`_tax_amounts_on_line`), and a head's label
# turns up in plenty of prose that carries no tax at all: the rule 46 footer
# "IGST is not applicable on intra-state supply as per Section 8", or the page
# footer "Page 1 of 2 - CGST/SGST summary continued on 22/09/2024". Matched with
# :data:`_NUMBER_PATTERN`, those lines are read as tax lines and the last number
# on them becomes the head's amount — the section number, or a fragment of a
# date. That footer put ₹2 of CGST and ₹2,024 of SGST on the invoice.
#
# And it is not merely noise, because the first reading of a head wins: the
# figures above are set before the real ``CGST @ 9% 9,000.00`` two lines down is
# ever reached, so the true amount is discarded in favour of the page number.
# Tax on the invoice read 2,026.00 instead of 18,000.00, on a document that
# parses perfectly otherwise.
#
# Requiring the shape rather than the position is what makes the distinction
# survive layouts this module has not seen: a date, a section number, a page
# count and a serial are all bare integers, and none of them can be mistaken for
# ₹9,000.00. The cost is an invoice printing a whole-rupee amount with neither
# separator nor decimals — "IGST 18000" — whose tax now reads empty rather than
# wrong, which is the trade this module makes everywhere else and the one
# ``validate_period`` reports as figures that do not foot.
_MONEY_FIGURE = re.compile(r"-?\d[\d,]*\.\d{1,2}|-?\d{1,3}(?:,\d{2,3})+")

# A separator that joins such a match to a further run of digits, which means
# the match is a piece of a longer thing rather than an amount in its own right.
#
# Requiring a money *shape* stops a bare integer being read as tax, but a date
# written with dots is money-shaped for as long as the pattern looks at it:
# ``22.09.2024`` offers ``22.09`` — two digits, a point, two more — and nothing
# about those five characters says they are a day and a month. The pattern stops
# there because a third group is not part of any amount, so the figure it hands
# back is the front of the date with the year left behind.
#
# That is the same failure the shape test was added to close, reached by the
# other date format. ``IGST is not applicable as per Section 8 dated 22.09.2024``
# read as ₹22.09 of IGST, and because a head is only read once, the real
# ``IGST @ 18% 81,000.00`` below it was then discarded — an invoice whose tax was
# out by ₹80,977 with nothing on the screen to say so.
#
# DD.MM.YYYY is ordinary on an Indian invoice, so this is not an exotic layout.
# The slash form never reached here — ``22/09/2024`` holds no point and no
# grouping, so it is not money-shaped to begin with — which is why the first
# pass missed it: the footer that prompted the fix happened to use slashes.
#
# Refused rather than trimmed, in the same spirit as :data:`_EXPONENT_SUFFIX`
# below: what follows the point is a year, not decimals, so there is no amount
# here to recover. Leaving the head empty is what lets ``validate_period`` say
# the figures do not foot, where ₹22.09 is a number nobody re-checks.
_JOINED_TO_DIGITS = re.compile(r"[./]\d")


def _money_figures_in(text: str) -> list[str]:
    """The money-shaped figures in *text*, minus the ones inside a date.

    See :data:`_MONEY_FIGURE` for what counts as money-shaped and
    :data:`_JOINED_TO_DIGITS` for what disqualifies a match that is.
    """
    return [
        match.group()
        for match in _MONEY_FIGURE.finditer(text)
        if not _JOINED_TO_DIGITS.match(text, match.end())
    ]


# An exponent immediately after such a match, which means the match is only the
# mantissa of a number the pattern above cannot express.
#
# The pattern is deliberately narrow — an invoice does not print ``2E5`` — but
# narrow is not the same as safe, because ``search`` returns a *prefix* rather
# than nothing. ``"1E+100"`` matched ``"1"``, so the ceiling in :func:`to_money`
# was handed the figure one and agreed with it: an amount a hundred orders of
# magnitude out did not fail a bound, it silently became a rupee. ``"1.5E+30"``
# became one rupee fifty.
#
# It is reachable from both directions. A model asked for JSON emits ``1e300``
# as a bare float — caught — but ``"1.2e5"`` as a string when it decides to
# quote its numbers, and a spreadsheet exported to CSV writes any wide column
# in exactly this form.
#
# So a truncated match is refused rather than used. Refusing leaves a zero and,
# on the model path, a warning naming what was dropped; using the mantissa
# leaves a plausible small number with nothing to show it was ever anything
# else. The first is a tax box a reviewer can see is empty, and the second is a
# figure nobody has any reason to look at twice.
_EXPONENT_SUFFIX = re.compile(r"[eE][+-]?\d")

# The number :func:`to_decimal` reads: :data:`_NUMBER_PATTERN` with every
# decimal digit rather than at most two.
#
# The two-digit cap is the same prefix problem as the exponent above, reached
# through the decimals. ``"12.345"`` came back as ``12.34`` — cut, not rounded —
# and :func:`normalize_rate` reads a value below one as a fraction, so a model
# that quoted ``"0.015"`` for the 1.5% slab had it cut to ``0.01`` and filed at
# 1%, and ``"0.001"`` (the 0.1% merchant-export rate) was cut to zero and filed
# as nil-rated. Line scanning keeps the narrower pattern; this is only the
# coercion of one value.
_FULL_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# A further ``.digit`` or ``,digit`` straight after such a match: a second
# decimal point (``1.234.567``) or a decimal comma (``1.234,56``, the European
# spelling of ₹1,234.56). Neither is a figure this product can read with any
# confidence, and reading the front of it is what turned ₹1,234.56 into ₹1.23.
# Refused for the reason the exponent is.
_TRAILING_GROUP = re.compile(r"[.,]\d")

_EXTRACTION_SCHEMA = """{
  "supplier_gstin": "15-char GSTIN of the party who issued the invoice, or null",
  "supplier_name": "legal or trade name of the issuer, or null",
  "buyer_gstin": "15-char GSTIN of the recipient, or null",
  "buyer_name": "name of the recipient, or null",
  "invoice_number": "the invoice/bill number exactly as printed, or null",
  "invoice_date": "YYYY-MM-DD, or null",
  "place_of_supply": "2-digit state code, or null",
  "hsn_code": "HSN/SAC of the main line item, or null",
  "taxable_value": "number, total value before tax",
  "cgst": "number, 0 if absent",
  "sgst": "number, 0 if absent",
  "igst": "number, 0 if absent",
  "cess": "number, 0 if absent",
  "total_value": "number, invoice grand total including tax",
  "tax_rate": "number as a percentage, e.g. 18, or null if the invoice mixes rates",
  "reverse_charge": "true only if the invoice says reverse charge applies",
  "line_items": [{"description": "string", "hsn_code": "string or null",
                  "quantity": "number or null", "taxable_value": "number",
                  "tax_rate": "number or null"}],
  "confidence": "number 0-1, how sure you are of the fields above"
}"""

_SYSTEM_PROMPT = (
    "You extract structured data from Indian GST tax invoices. "
    "You reply with one JSON object and nothing else — no prose, no markdown fence. "
    "Copy values exactly as printed; never invent a GSTIN, an invoice number or an amount. "
    "Use null for anything the document does not show. "
    "Amounts are plain numbers without currency symbols, commas or spaces. "
    "On an intra-state invoice tax is split into CGST and SGST and IGST is 0; "
    "on an inter-state invoice the whole tax is IGST and CGST/SGST are 0."
)


@dataclass
class ParsedInvoice:
    """What the extractors agreed on, plus how it was obtained."""

    supplier_gstin: str | None = None
    supplier_name: str | None = None
    buyer_gstin: str | None = None
    buyer_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    place_of_supply: str | None = None
    hsn_code: str | None = None
    taxable_value: Decimal = Decimal("0.00")
    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    cess: Decimal = Decimal("0.00")
    total_value: Decimal = Decimal("0.00")
    tax_rate: Decimal | None = None
    reverse_charge: bool = False
    line_items: list[dict] = field(default_factory=list)

    raw_text: str = ""
    parsed_with: str = "heuristic"
    confidence: float = 0.0
    # Human-readable problems: an unbalanced total, an invalid GSTIN, a rate
    # that is not a real GST rate. Shown to the user, never a reason to drop
    # the invoice — a flagged invoice can be corrected, a rejected one is
    # retyped from paper.
    warnings: list[str] = field(default_factory=list)

    @property
    def total_tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess

    @property
    def period(self) -> str | None:
        """Filing period as ``YYYY-MM``."""
        return self.invoice_date.strftime("%Y-%m") if self.invoice_date else None

    def as_dict(self) -> dict:
        """JSON-safe view, for storing on the invoice row."""
        return {
            "supplier_gstin": self.supplier_gstin,
            "supplier_name": self.supplier_name,
            "buyer_gstin": self.buyer_gstin,
            "buyer_name": self.buyer_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "place_of_supply": self.place_of_supply,
            "hsn_code": self.hsn_code,
            "taxable_value": str(self.taxable_value),
            "cgst": str(self.cgst),
            "sgst": str(self.sgst),
            "igst": str(self.igst),
            "cess": str(self.cess),
            "total_value": str(self.total_value),
            "tax_rate": str(self.tax_rate) if self.tax_rate is not None else None,
            "reverse_charge": self.reverse_charge,
            "line_items": self.line_items,
            "confidence": self.confidence,
            "parsed_with": self.parsed_with,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------
# Coercion helpers — everything below tolerates whatever a model or an OCR
# pass produced, because the alternative is a 500 on a blurry photograph.
# --------------------------------------------------------------------------

def to_decimal(value: object, default: Decimal | None = Decimal("0.00")) -> Decimal | None:
    """Coerce a model/OCR value to Decimal, or *default* if it is not a number.

    Handles the Indian digit grouping (``1,23,456.00``) and stray currency
    symbols, both of which appear constantly in extracted text.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    if isinstance(value, int | float):
        # ``Decimal(str(inf))`` is ``Decimal('Infinity')``, which is a Decimal
        # and is not a number anything here can do arithmetic with. It is
        # reachable: ``json.loads`` accepts the bare ``Infinity`` and ``NaN``
        # tokens by default, so a portal export or a model response containing
        # one arrives as a float and would be coerced rather than rejected.
        coerced = Decimal(str(value))
        return coerced if coerced.is_finite() else default
    # Match the number rather than stripping non-digits: stripping leaves the
    # full stop in "Rs. 1000.50" behind, and ".1000.50" is not a Decimal.
    text = str(value)
    match = _FULL_NUMBER.search(text)
    if match is None:
        return default
    # Only the front of a longer number was matched, so the digits in hand are
    # not the figure. See :data:`_EXPONENT_SUFFIX` and :data:`_TRAILING_GROUP`.
    if _EXPONENT_SUFFIX.match(text, match.end()) or _TRAILING_GROUP.match(text, match.end()):
        return default
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return default


def to_money(value: object, default: Decimal | None = Decimal("0.00")) -> Decimal | None:
    """Coerce *value* to an amount a money column can hold, or *default*.

    :func:`to_decimal` answers "is this a number"; this answers "is this an
    amount", and the two are not the same question. ``Numeric(16, 2)`` holds
    fourteen digits before the point, and nothing above that is a figure any
    invoice carries — but every door into this product would take one. A model
    asked for JSON can emit ``1e300``; a hand-edited GSTR-2B can carry a run of
    forty digits; ``json.loads`` will hand over a bare ``Infinity``.

    What made it worth a check of its own is where the failure lands. The write
    succeeds — Postgres refuses the INSERT, but SQLite keeps whatever it was
    handed, so the two backends disagree about whether there is a problem at
    all — and the *read* is what breaks. Every figure in this product is
    quantized to the paisa on its way out, and ``Decimal.quantize`` raises
    ``InvalidOperation`` rather than rounding once a result needs more than the
    context's 28 significant digits. So one overlarge amount is not a wrong
    number on one screen: it is a 500 on the dashboard, the ITC summary and the
    GSTR-3B preview, for as long as the row is there, caused by a write that
    answered 200.

    Out of range is discarded rather than clamped. Clamping invents a figure of
    ninety-nine thousand crore and files it; discarding leaves the field at
    zero where a reviewer can see it is missing, which is the same trade the
    parser already makes for a GSTIN it cannot believe.
    """
    coerced = to_decimal(value, default=None)
    if coerced is None or not coerced.is_finite() or abs(coerced) > MONEY_MAX:
        return default
    return coerced


# What a document, a portal export or a model says for "no" — and for "yes".
# Kept as sets rather than as a regex because these are whole answers, not
# substrings: "not applicable" must not be read as the "applicable" inside it.
_TRUE_WORDS = frozenset({"Y", "YES", "TRUE", "1", "APPLICABLE", "T", "AVAILABLE"})
_FALSE_WORDS = frozenset(
    {
        "N", "NO", "FALSE", "0", "F", "NA", "N/A", "NOT APPLICABLE", "NONE", "NIL", "-",
        # The wording a GSTR-2B uses for its own "no", where the question is
        # whether credit may be claimed rather than whether a clause applies.
        # These used to live in a second, smaller set private to the GSTR-2B CSV
        # reader; they belong here because the answer means the same thing
        # whoever is asking. "Available" is their opposite and joins the true
        # words for the same reason.
        "NOT AVAILABLE", "UNAVAILABLE",
    }
)


def to_flag(value: object, *, default: bool = False) -> bool:
    """Read a yes/no answer, whoever wrote it, or *default* if it is neither.

    ``bool()`` is not this function. It says a non-empty string is true, and
    the strings that arrive here are overwhelmingly the *word* for false:
    "reverse charge: Not Applicable" is printed on a large share of Indian tax
    invoices, and a model asked to copy what the document says copies that.
    Read with ``bool()``, every one of those invoices came back flagged reverse
    charge — which is not a cosmetic mislabel. It moves the tax to table 3.1(d)
    of GSTR-3B as a liability the business must settle in cash, takes the
    invoice's credit out of the pool it belongs in, and on a *sale* prints
    ``rchrg: "Y"`` in the buyer's GSTR-2B, telling a customer they owe tax the
    supplier has already charged them.

    An answer that is neither falls back to *default* rather than guessing,
    which is how the portal's own ``itcavl`` flag keeps defaulting to "credit
    is available" while ``rev`` keeps defaulting to "no".
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | Decimal):
        return bool(value)
    text = re.sub(r"\s+", " ", str(value)).strip().upper()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return default


def to_date(value: object) -> date | None:
    """Parse the date formats that appear on Indian invoices.

    ``DD/MM/YYYY`` is the local convention and ``MM/DD/YYYY`` is what a model
    trained mostly on US documents may emit, so an ambiguous ``03/04/2026`` is
    read day-first. It is the right call more often here, and the day-vs-month
    ambiguity only ever shifts the filing period by a month rather than
    corrupting the amount.

    Preferring day-first is not the same as refusing month-first, and for a
    while this read it as such: every format tried was day-first, so
    ``12/31/2024`` matched none of them and the invoice came back with no date
    at all. That is the more expensive outcome of the two. A date read a month
    out files the invoice in the neighbouring return; a date not read at all
    takes the invoice out of *every* return, and :func:`validate` says as much
    — the field alone decides which period the invoice appears in, and an
    invoice in no period leaves the register, the dashboard and the GSTR-1
    together with nothing downstream left to notice.

    So the day-first formats are tried first and month-first is the fallback,
    which costs nothing in ambiguity: a two-part numeric date only reaches the
    fallback when the day-first reading was *invalid*, and the first field
    being above 12 means it was never a month. ``12/31/2024`` has exactly one
    reading and now gets it, while ``03/04/2026`` still matches day-first in
    the first pass and never reaches here.
    """
    # datetime subclasses date, so it has to be narrowed first — the other
    # order makes this branch unreachable and returns the datetime unchanged,
    # which is not what the signature promises and puts a time on a column
    # that has no room for one.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    day_first = (
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
        "%d-%m-%y", "%d/%m/%y", "%d-%b-%Y", "%d %b %Y", "%d %B %Y",
        "%Y/%m/%d",
    )
    month_first = (
        "%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y",
        "%m/%d/%y", "%m-%d-%y",
        "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y",
    )
    for fmt in day_first + month_first:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean_str(value: object, max_length: int = 255) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text.lower() in {"null", "none", "n/a", "na", "-"}:
        return None
    return text[:max_length]


def normalize_rate(value: object) -> Decimal | None:
    """Coerce a tax rate, dropping anything that is not a real GST rate.

    Public because :mod:`app.services.filing` reads the same rates back off a
    stored ``line_items`` breakdown when it builds a return, and "what counts as
    a rate" must not be answered twice.

    A model asked for "18" sometimes answers "0.18", so a value below 1 is
    read as a fraction and scaled — but only when it is not already a rate in
    its own right. Scaling first made the sub-1% slabs unreachable: 0.25 is a
    real GST rate, it sits in :data:`VALID_TAX_RATES` a few lines above, and it
    was multiplied into 25 — which is not a slab at all — and then discarded.
    An invoice on rough diamonds could therefore never carry its own rate,
    however plainly the document printed it.

    Reading the literal first is unambiguous rather than merely safer, because
    the two readings never both land on a slab. 0.25 as a fraction is 25%, and
    0.1 as a fraction is 10%; neither is a rate GST levies, so preferring the
    literal costs nothing anywhere it does not gain a real one.

    That ordering is also why the fraction window below leaves a mutation
    survivor on each of its two comparisons. Both of its edges are themselves
    slabs — 0% is nil-rated and 1% is levied — so the membership check above
    has already returned by the time either edge could be tested, and neither
    ``<`` can be widened to ``<=`` by anything a caller can pass. The edges are
    unreachable rather than unasserted.
    """
    rate = to_decimal(value, default=None)
    if rate is None:
        return None
    if rate in VALID_TAX_RATES:
        return rate
    if Decimal("0") < rate < Decimal("1"):
        rate = rate * 100
    return rate if rate in VALID_TAX_RATES else None


# --------------------------------------------------------------------------
# Heuristic extractor
# --------------------------------------------------------------------------

# "Invoice No.: INV-001" and the dozen other ways a document says the same
# thing. Two details are load-bearing, both learned from the same failure.
#
# The separator is a *run* rather than one character. Invoices write "No.:",
# "No :-", "NO. : " and a bare space, and a pattern accepting exactly one
# punctuation mark matched none of them. That alone would only lose the number
# — but losing it here is not what happened, because `search` does not stop at
# a label that failed. It slid down the line and matched the `inv` alternative
# against the *value*: "Invoice No.: INV-001" found "INV", took the hyphen as
# its separator, and returned "001". The number was not missing, it was
# silently wrong, and a wrong invoice number is the one field that cannot be
# caught downstream — it files into GSTR-1 as the customer's evidence, it is
# what reconciliation matches a GSTR-2B row on, and it is what duplicate
# detection keys on. All three fail quietly and separately.
#
# So the bare hyphen is only a separator *after* an explicit "no"/"number"/
# "#" token, which is what establishes that a label was read at all. Without
# one, "INV-001" standing alone in the text no longer parses as the number
# "001" — it does not parse, and an empty field with a warning on it is a
# reviewable state in a way that a plausible wrong number is not.
#
# That same token is what makes a *one-character* number safe, and the two
# branches below differ only in whether they allow one. "Invoice No: 7" is how
# a business in its first month of trading prints an invoice, and a single
# minimum length of two characters dropped the number from every one of them —
# silently, because there is nothing to see afterwards. A missing invoice
# number is not a cosmetic loss: it files into GSTR-1 as ``inum: ""``, which
# the portal rejects; it is what reconciliation matches a GSTR-2B row on; and
# it is half the natural key duplicate detection uses. All three fail
# separately.
#
# The bare-separator branch keeps the two-character floor, because there the
# label was never confirmed and a single stray character after a full stop is
# noise rather than a document number.
#
# Every gap in the pattern is horizontal space, so the label, its separator and
# the value stay on one line. Written with a plain ``\s`` the separator run
# crossed the line break and took the first word of the *next* line as the
# number, which is how a document that prints its label with no value beside it
# — a column heading, or a wrapped line — came out with an invoice number of
# "Date", "Bill", "Total" or "of":
#
#     Invoice No.                 ->  "Date"
#     Date: 02/05/2026
#
#     TAX INVOICE                 ->  "of"
#     No. of Packages: 12
#
# Both are the silently-wrong number this pattern exists to prevent, and worse
# than the reading it was written to stop, because "of" is not even a document
# number: it files into GSTR-1 as ``inum``, it is what reconciliation matches a
# GSTR-2B row on, and it is half the key duplicate detection uses.
#
# The cost of the restriction is a layout that prints the heading and the value
# on separate rows, which now reads no number at all. That layout was never read
# correctly anyway — a header row carries the *next* label, not the value, so
# "Invoice No.  Invoice Date" over "MH/2026/118  02/05/2026" returned the word
# "Invoice" — and a blank a reviewer can see beats a word that looks like data.
_SAME_LINE_SPACE = r"[^\S\r\n]"

# "Bill of Supply" is in the label because it is a document in its own right.
# Rule 49 has it in place of a tax invoice for exempt supplies and for every
# supply a composition dealer makes, so a business on the composition scheme
# issues nothing else — and the words between "Bill" and "No" meant the number
# was never found on any of them.
_INVOICE_NO_PATTERN = re.compile(
    rf"(?:tax{_SAME_LINE_SPACE}+invoice|invoice|inv"
    rf"|bill(?:{_SAME_LINE_SPACE}+of{_SAME_LINE_SPACE}+supply)?)(?:{_SAME_LINE_SPACE}|\.)*"
    r"(?:"
    rf"(?:no|number|num|#)(?:{_SAME_LINE_SPACE}|[:.\-#])*"
    # One label for two fields: "Invoice No. & Date : INV-42 dt. 15/04/2026"
    # prints the number and the date of issue under a single heading, which is
    # how most tabular Indian templates head the band. Without this the "&" is
    # not a separator character, the value group met it instead of the number,
    # and the whole match failed — so the field was empty on every document
    # printed that way. The date half of the same line is
    # :data:`_JOINED_DATE_PATTERN`.
    #
    # The second label is required after the conjunction rather than optional,
    # so this absorbs only a joined heading. A bare "&" left to be skipped
    # would step over whatever an invoice prints between the label and its
    # value, which on the layouts here is another document's number.
    rf"(?:(?:&|and)(?:{_SAME_LINE_SPACE})*(?:date|dt)\b(?:{_SAME_LINE_SPACE}|[:.\-#])*)?"
    r"([A-Za-z0-9][A-Za-z0-9\-/]{0,29})"
    r"|"
    rf"[:.#](?:{_SAME_LINE_SPACE}|[:.\-#])*([A-Za-z0-9][A-Za-z0-9\-/]{{1,29}})"
    r")",
    re.IGNORECASE,
)


# The other document that is printed on the face of an invoice and numbered
# like one.
#
# An e-way bill is required for most consignments above ₹50,000, and its number
# is printed at the top of the invoice it accompanies — usually above the
# invoice's own number, in the same block as the IRN. "Bill" is one of the
# labels :data:`_INVOICE_NO_PATTERN` reads, and nothing in it cared what came
# before, so "E-Way Bill No: 123456789012" gave the invoice a number that
# belongs to a transport document.
#
# That is the cited-number failure again with a different source, and it lands
# the same way: a twelve-digit number is a plausible invoice number, so GSTR-1
# files the supply under it, the supplier's real 2B row matches nothing, and
# duplicate detection keys on a value that changes with every consignment.
#
# All five spellings appear in the wild, and one of them is closed up, so the
# space between "way" and "bill" has to be optional — the pattern matches the
# "bill" *inside* "Waybill" just as happily.
# The trailing "bill" is optional because this guard is used before two
# different labels. The number is read from "E-Way Bill No", where "Bill" is
# the label itself and the text before it ends at "Way"; the date is read from
# "E-Way Bill Date", where "Bill Date" is the label and the text before it ends
# at "Way Bill". Without it the date pattern walked straight through the guard
# — see :func:`_invoice_date_in`.
_EWAY_PREFIX = re.compile(
    rf"\b(?:e[\s.\-]*)?way(?:{_SAME_LINE_SPACE}|[.\-])*(?:bill(?:{_SAME_LINE_SPACE}|[.\-])*)?$",
    re.IGNORECASE,
)


# Wording that marks the number after it as *another* document's.
#
# An invoice cites other invoices. A credit or debit note must carry the
# original invoice's number to be valid at all under rule 53, a revised invoice
# names the one it replaces, and an ordinary invoice for continuing work often
# opens "Against our Invoice No: ...". Every one of those prints a second, older
# document number *above* the document's own — and :func:`_invoice_number_in`
# took the leftmost match, so on all of them the number stored was the one being
# referred to rather than the one being read.
#
# That is the failure :data:`_INVOICE_NO_PATTERN` above calls the one that
# cannot be caught downstream, reached by a different route. Worse here than a
# missing number, because the value is not merely wrong but is a real invoice
# number belonging to a real earlier document: reconciliation matches it against
# that document's GSTR-2B row, duplicate detection sees the earlier invoice
# already filed under it, and GSTR-1 files two different supplies under one
# ``inum``. Nothing in that chain has any reason to look twice.
#
# The marker has to sit immediately before the label — reference word, at most a
# "to" and an "our"/"your"/"the", then the label itself. Scanning the whole line
# instead would read the triplicate marking every Indian invoice is printed with,
# "ORIGINAL FOR RECIPIENT", as a reference to an original *invoice*, and drop
# the document's own number from a layout that puts that marking in the same
# band as the number. Requiring adjacency tells "Original Invoice No: 41" from
# "ORIGINAL FOR RECIPIENT    Invoice No: 41", which no window of characters can.
#
# "Revised" is deliberately *not* in the list, though it names the same relation
# as the rest. Rule 53(1) has the revised document headed "Revised Invoice" and
# carrying its own serial, with the document it replaces named separately as the
# original — so on a revised invoice "Revised Invoice No: R-9" is the number
# being read, not a reference, and skipping it would take the number off every
# revised invoice to save a reference that is spelt "Original Invoice No" anyway.
#
# A document whose only number is a referenced one is left with none, in the
# same spirit as the rest of this module: an empty field a reviewer can see
# beats a plausible number belonging to something else.
_REFERENCE_PREFIX = re.compile(
    r"(?:"
    # "w.r.t.", "w r t", "wrt" — spelled out rather than folded into the word
    # list below because the trailing \b would fall after a full stop.
    r"\bw\.?\s*r\.?\s*t\.?"
    r"|\b(?:against|ref|refer(?:ence|ring)?|original|orig|previous|prev|vide)\b"
    r")"
    # "with reference to your Invoice No." is how the wording is actually
    # printed as often as the bare form, so the optional "to" is not a nicety.
    r"[\s:.\-]*(?:to\b)?[\s:.\-]*(?:our|your|the)?[\s:.\-]*"
    # The document being cited may be named between the marker and the label,
    # which happens whenever the label does not name it itself. The number is
    # read from "Original Invoice No", where the noun belongs to the label and
    # the text before it ends at "Original"; the date is read from "Original
    # Invoice Date", where the loose label is the bare "Date" and the noun is
    # left in the text before it. Optional, so both windows still match.
    r"(?:(?:tax|credit|debit|delivery)?[\s.\-]*(?:invoice|inv|bill|note|challan)\b)?"
    r"[\s:.\-]*$",
    re.IGNORECASE,
)


# How far back from a label the prefix guards look. They are anchored to the
# text immediately before it (``$``), so what matters is the last few words; the
# longest prefix that means anything — "with reference to your tax invoice" plus
# its separators — is well under this.
#
# Bounded because the window was the whole line, and every candidate searched
# it again: a document of one long line repeating a label that never yields a
# value (an e-way bill number, a label with nothing after it) cost time
# quadratic in its length — 7 s at 50 KB, the better part of an hour at the
# 2 MB text ceiling — on a worker, retried four times. ``search(text, pos)``
# still sees the characters before ``pos`` for ``\b``, so a window that starts
# mid-word cannot invent a word boundary.
_PREFIX_WINDOW = 160


def _before(text: str, end: int) -> tuple[int, int]:
    """The span the prefix guards search: this line, at most a window back."""
    line_start = text.rfind("\n", max(0, end - _PREFIX_WINDOW), end) + 1
    return max(line_start, end - _PREFIX_WINDOW), end


def _invoice_number_in(text: str) -> str | None:
    """The document number the text labels, or ``None``.

    The pattern has two value groups — see :data:`_INVOICE_NO_PATTERN` — and
    exactly one of them is filled on any match, so the caller should not have
    to know which branch fired.

    Matches belonging to another document are passed over — one cited as a
    reference, one carrying the consignment's e-way bill number. See
    :data:`_REFERENCE_PREFIX` and :data:`_EWAY_PREFIX` for what counts as
    either, and why both are anchored to the text immediately before the label.

    A word is passed over too — two or more characters with no digit among
    them. What such a candidate actually is, on every document that produced
    one, is the next label on a line that printed its own label with nothing
    beside it: a tabular layout heading its columns ``Invoice No.   Invoice
    Date`` yielded the number "Invoice", and the same shape yields "Date",
    "Total", "E-Way" or "of". Each is a plausible-looking string in the one
    field nothing downstream can check, so none is worth having over an empty
    field a reviewer can see. Placeholders — "NA", "TBD" — go the same way, and
    should: rule 46(b) makes the number a consecutive serial and neither is one.

    A *single* character is kept even when it is a letter, because it can only
    have come through the branch that confirmed a "No"/"#" token before it —
    see :data:`_INVOICE_NO_PATTERN` — and one letter standing in the value
    position of a confirmed label is a first-year series, not a column heading.
    """
    for match in _INVOICE_NO_PATTERN.finditer(text):
        before = _before(text, match.start())
        if _REFERENCE_PREFIX.search(text, *before) or _EWAY_PREFIX.search(text, *before):
            continue
        # Well clear of anything the pattern can hand over: both of its value
        # groups are capped at thirty characters, so this truncation has never
        # fired and the mutation survivor on the length is an equivalent one.
        # Kept as the module-wide backstop against a stored field of unbounded
        # length, which is the same reason :func:`_clean_str` has a default.
        value = _clean_str(match.group(1) or match.group(2), 64)
        if value is None:
            continue
        if len(value) > 1 and not any(char.isdigit() for char in value):
            continue
        return value
    return None


# A date, in any of the shapes :func:`to_date` knows how to read.
_DATE_VALUE = r"(\d{1,4}[-/.\s][A-Za-z0-9]{1,9}[-/.\s]\d{2,4})"

# Two patterns rather than one, tried in this order, because an invoice prints
# more than one date and only one of them decides the filing period.
#
# A bare "date" label matches "Due Date" as happily as "Invoice Date" — and a
# payment due date is normally printed *above* the invoice date, so the
# leftmost match is the wrong one. The invoice then files under the month it
# has to be paid in rather than the month it was issued in: one period late,
# in a return that has already been filed by the time anyone reconciles it.
#
# So an explicit invoice-date label wins wherever the document carries one, and
# the loose label is the fallback for documents that only say "Date:". The
# separator is a run for the same reason as in the invoice number above —
# "Date.:" and "DATE. : " are both printed.
#
# Ordering the two is necessary and not sufficient: it settles which label wins
# only on a document that prints the explicit one. Which of several *matches*
# is the invoice's own is decided in :func:`_invoice_date_in`, and the explicit
# pattern needs that as much as the loose one — "E-Way Bill Date" ends in one
# of the labels here, and "Original Invoice Date" in another.
#
# "Date of Issue" belongs here rather than in the loose pattern for the same
# reason "Date of Invoice" already does: it names the invoice's own date as
# specifically as "Invoice Date" does, in the wording rule 46(f) itself uses —
# "date of its issue" — so a template built against the rule text prints this
# rather than the more colloquial label. Left in the loose pattern's care, "of
# Issue" is not one of the separator characters between "Date" and the value,
# so the label did not merely lose its ranking — it failed to match at all, and
# the field fell through to whatever a due date or an e-way bill printed above
# it, or to no date if the document had neither.
_DATE_PATTERN = re.compile(
    r"(?:invoice\s*date|date\s+of\s+(?:invoice|issue)|bill\s*date)[\s:.\-]*" + _DATE_VALUE,
    re.IGNORECASE,
)
_LOOSE_DATE_PATTERN = re.compile(
    r"(?:dated|date)[\s:.\-]*" + _DATE_VALUE,
    re.IGNORECASE,
)

# The date half of a heading that names both fields at once — "Invoice No. &
# Date : INV-42 dt. 15/04/2026". The number half is in
# :data:`_INVOICE_NO_PATTERN`.
#
# Neither pattern above can reach this date. The explicit one wants "Invoice
# Date" with nothing but space between the two words, and here the number's
# label is in between. The loose one matches the "Date" of the heading itself
# and then requires the value to follow the separators — but what follows is
# the *number*, so the match fails there and the document was left with no
# date at all. That is the expensive half of this layout: the date decides the
# period, so an invoice that loses it is one nothing files in any month.
#
# Ranked with the explicit pattern rather than the loose one because the
# heading names the invoice's own date as plainly as "Invoice Date" does. A
# document printing this and a due date must not read the due date, which is
# what being second to the loose pattern would eventually cost it.
#
# Only the heading is matched here. What follows it is the number and then the
# date, punctuated "dt.", "dated", "/" or not at all, and the date is picked
# out of the rest of the line by :func:`_date_candidates` rather than by more
# pattern — because the number in between is itself full of date-shaped digit
# groups. A series like "NW/26-27/0042" contains "26-27/0042", which matches
# :data:`_DATE_VALUE` and is not a date, so a single expression that took the
# first shape on the line would come back empty on exactly the
# series/year/serial numbering these headings are usually printed with.
_JOINED_HEADING_PATTERN = re.compile(
    r"(?:tax\s*)?(?:invoice|inv|bill)\s*(?:no|number|num|#)[\s.]*"
    r"(?:&|and)\s*(?:date|dt)\b",
    re.IGNORECASE,
)

# The date shape on its own, for scanning a line the heading above has claimed.
_DATE_VALUE_PATTERN = re.compile(_DATE_VALUE)


# Wording that marks the date after it as something other than the date of
# issue — another document's date, or another event in this one's life.
#
# Ordering the two patterns above answers "Due Date" only on a document that
# also prints an explicit invoice-date label. On one that labels its own date
# "Date:" — which is the common case the loose pattern exists for — the due
# date is still printed first, still matches, and still wins on being leftmost.
# So the invoice files under the month it must be *paid* in: one period late,
# in a return already filed by the time anyone reconciles it.
#
# The same holds for every other date an invoice prints beside its own. A
# purchase order and a delivery challan predate the supply, an e-invoice
# acknowledgement and a lorry receipt follow it, and each is printed in the
# same block. All of them are the wrong month often enough to matter, and one
# is wrong in the expensive direction: a PO date can sit a quarter earlier,
# in a period whose return is long filed.
#
# Anchored immediately before the label, for the reason given at
# :data:`_REFERENCE_PREFIX` — a marker loose on the line reads the wrong one.
# "Supply" is here because rule 47 allows an invoice to be issued up to thirty
# days after the supply it bills, so the two dates are not the same date and
# the difference crosses a month whenever the supply falls near its end.
_OTHER_DATE_PREFIX = re.compile(
    r"(?:"
    # "P.O." and "L.R." are spelled out rather than folded into the word list
    # below because the trailing \b would fall after a full stop.
    r"\bp\.?\s*o\.?"
    r"|\bl\.?\s*r\.?"
    r"|\b(?:due|ack(?:nowledge?ment)?|challan|delivery|deliver(?:ed)?"
    r"|dispatch|despatch|order|payment|receipt|supply|transport|irn)\b"
    r")"
    r"[\s:.\-]*$",
    re.IGNORECASE,
)


def _date_candidates(text: str) -> Iterator[tuple[int, str]]:
    """Every labelled date in *text*, in the order the labels rank.

    Yields ``(label_start, value)``: the offset the markers in
    :func:`_invoice_date_in` are measured back from, and the string to parse.
    The label rather than the value is what those markers sit before, and on a
    joined heading the two are not in the same place — which is the whole
    reason this hands back a position instead of a match.
    """
    for match in _DATE_PATTERN.finditer(text):
        yield match.start(), match.group(1)
    # A joined heading labels the number and the date together, so the date sits
    # past the number rather than beside the label. Every date-shaped run on the
    # rest of the line is offered, not just the first, because the number being
    # stepped over is itself full of digit groups — see
    # :data:`_JOINED_HEADING_PATTERN`. The unparseable ones fall away in the
    # caller, which already passes over a shape that is not a date.
    for heading in _JOINED_HEADING_PATTERN.finditer(text):
        line_end = text.find("\n", heading.end())
        line_end = len(text) if line_end == -1 else line_end
        # Every offset, rather than ``finditer``, because the shapes here
        # overlap and the ones that are not dates have to be able to fail
        # without taking a real date with them. On "INV-2026-0042 dt
        # 15.04.2026" the shape starting at "0042" runs "0042 dt 15" — it
        # spans the serial, the marker and the day — so a non-overlapping scan
        # resumes past the day and never offers "15.04.2026" at all. The line
        # is one line, so this stays a scan of a hundred-odd offsets.
        for start in range(heading.end(), line_end):
            if (value := _DATE_VALUE_PATTERN.match(text, start, line_end)) is not None:
                yield heading.start(), value.group(1)
    for match in _LOOSE_DATE_PATTERN.finditer(text):
        yield match.start(), match.group(1)


def _invoice_date_in(text: str) -> date | None:
    """The date of issue the text labels, or ``None``.

    Six things are tried in order, and the first that yields a date wins: an
    explicit invoice-date label, a heading naming the number and the date
    together, a loose label, then — only if none produced a usable date — the
    same three again allowing labels that mark the date as another document's.

    That last tier is why a marked date is passed over rather than refused. A
    document whose *only* date is a due date still gets one, which is the
    behaviour the loose pattern was added for; what changes is that such a date
    can no longer beat the document's own date to being read, which is what
    being leftmost used to buy it. See :data:`_OTHER_DATE_PREFIX`, and
    :data:`_REFERENCE_PREFIX` and :data:`_EWAY_PREFIX` for the two markers this
    shares with the invoice number — a credit note carries the original
    invoice's date under rule 53, and the e-way bill prints its own beside it.

    A match whose value does not parse is passed over too. ``_DATE_VALUE``
    matches a shape rather than a date, so "12/ABC/34" can match and yield
    nothing; taking it and stopping would blank a field that a real date
    further down the page would have filled.
    """
    marked: list[str] = []
    for start, raw in _date_candidates(text):
        before = _before(text, start)
        if (
            _OTHER_DATE_PREFIX.search(text, *before)
            or _REFERENCE_PREFIX.search(text, *before)
            or _EWAY_PREFIX.search(text, *before)
        ):
            marked.append(raw)
            continue
        if (value := to_date(raw)) is not None:
            return value
    for raw in marked:
        if (value := to_date(raw)) is not None:
            return value
    return None
# The separator before an amount admits a hyphen, because "Total - 5,000.00" is
# printed — and that is the same character a negative amount begins with. With
# nothing to tell them apart the separator ate the sign: "Taxable Value
# -5,000.00" matched with the hyphen as punctuation and handed back 5,000.00,
# the figure with its sign removed rather than the figure.
#
# A flipped sign is the worst of the three outcomes available here. Read as
# -5,000 it is a credit note this product does not model and every screen shows
# a negative; left unread it is an empty box a reviewer can see; read as +5,000
# it is an ordinary-looking invoice that states the opposite of the paper, and
# nothing downstream re-derives it. A credit note booked as a supply overstates
# turnover in GSTR-1 and, on the purchase side, claims credit the note was
# issued to take back.
#
# So the sign may not be consumed as punctuation: the amount must not be
# preceded by a minus attached to it. A hyphen with a space after it is still a
# separator — "Total - 5,000.00" reads as before — and "Total -5,000.00" now
# matches nothing at all, which is this module's standing preference for an
# empty field over a plausible wrong one. The negative forms never parsed to a
# negative *here* in any case: ``_AMOUNT`` has no sign to capture, so the only
# readings ever available were "positive" and "nothing".
_AMOUNT = r"(?<!-)([0-9][0-9,]*\.?\d{0,2})"
# Whole-word labels, matched per line. Anchored on ``\b`` so "GSTIN" can never
# be read as a tax line, and kept separate from the amount so that the rate in
# "IGST @ 18%: 81000.00" cannot be mistaken for the amount — which is what
# happens to any pattern that simply takes the first number after the label.
_TAX_LABELS = {
    "cgst": re.compile(r"\bCGST\b", re.IGNORECASE),
    "sgst": re.compile(r"\bSGST\b", re.IGNORECASE),
    "igst": re.compile(r"\bIGST\b", re.IGNORECASE),
    "cess": re.compile(r"\bCESS\b", re.IGNORECASE),
}
_PERCENT_PATTERN = re.compile(r"(\d{1,2}(?:\.\d{1,2})?)\s*%")

# Both money labels below are spaced with :data:`_SAME_LINE_SPACE` rather than
# ``\s``, for the reason the tax labels above are read a line at a time: a label
# and its amount sit on one line, and ``\s`` does not stop at the line break.
#
# What that cost was a summary block printed as two columns — headings on one
# line, their figures on the next, which is how a great many tax invoices print
# it:
#
#     Taxable Value:      Grand Total:
#     1,00,000.00         1,18,000.00
#
# "Grand Total:" matched, ``\s*`` walked over the line break, and the first
# amount it reached was the one under the *other* heading. The grand total was
# stored as the taxable value — understated by exactly the tax. "Taxable
# Value:" meanwhile matched nothing, because the words "Grand Total:" stood
# between it and any figure, so it stayed at zero.
#
# Nothing said so. The footing check in :func:`validate` is the one thing that
# would have caught a total that is not taxable plus tax, and it only runs when
# both figures are non-zero — so the zero this left behind is exactly what
# switched off the check that would have found it. The invoice stored ₹0
# taxable against ₹18,000 of tax and filed at the wrong invoice value, with no
# warning on the review screen to say a figure had been read from the wrong
# column.
#
# "Assessable Value" is customs' own name for the figure duty is charged on —
# rule 3 of the Customs Valuation Rules uses it, so an import invoice, or one
# from a supplier whose template also handles imports, prints this rather than
# "Taxable Value". Left out, the field was not merely misread: a document
# whose IGST read correctly (:data:`_TAX_LABELS` matches "IGST" on its own
# line regardless of what the taxable line said) stored ₹0 taxable value
# beside a real tax figure, which is the shape ``validate_period``'s footing
# check exists to catch and cannot here — that check only runs when *both*
# figures are non-zero.
_TAXABLE_PATTERN = re.compile(
    rf"(?:taxable{_SAME_LINE_SPACE}*(?:value|amount)"
    rf"|assessable{_SAME_LINE_SPACE}*value"
    rf"|sub{_SAME_LINE_SPACE}*-?{_SAME_LINE_SPACE}*total"
    rf"|net{_SAME_LINE_SPACE}*amount)"
    rf"{_SAME_LINE_SPACE}*[:.\-]?{_SAME_LINE_SPACE}*"
    rf"(?:INR|Rs\.?|₹)?{_SAME_LINE_SPACE}*{_AMOUNT}",
    re.IGNORECASE,
)

# "Net Payable" and a bare "Total" join the labels already here for the same
# reason "Assessable Value" was added above: a real wording this pattern did
# not know, silently leaving the grand total at ₹0 on a document that
# otherwise parses.
#
# A bare "Total" needs a guard the others do not. Unlike "Grand Total" or
# "Invoice Total", the word "Total" alone also opens "Total Tax", "Total
# Discount" and "Sub-Total" — and unlike those two, "Sub-Total" is a real label
# read by :data:`_TAXABLE_PATTERN` above with a *different* figure. Matched
# without a guard, "Total" inside "Sub-Total: 200000.00" is exactly as valid a
# match as a real total line, and being earlier in the text it would win over
# the actual "Amount Payable: 236000.00" a few lines down — replacing the
# grand total with the taxable value it was computed from, on a layout that
# otherwise parses every other field correctly.
#
# Anchoring to the start of a line closes that without a lookbehind for every
# spelling of "sub" (which Python's fixed-width lookbehind cannot express as
# one alternative anyway): a real total label is always the first word on its
# line, and "Sub-Total" is not — "Total" there is the second half of a
# hyphenated word, never the first token after a line break. The other three
# guards this module leans on for a bare word — "Total Tax", "Total Discount",
# "Total Quantity" — need no anchor at all, because the shared amount suffix
# below already requires a separator or a currency mark immediately after the
# label, and none of those three has one: the word that follows is not a
# number, so the match fails right there regardless of position on the line.
_TOTAL_PATTERN = re.compile(
    rf"(?:grand{_SAME_LINE_SPACE}*total"
    rf"|total{_SAME_LINE_SPACE}*(?:invoice{_SAME_LINE_SPACE}*)?(?:value|amount)"
    rf"|amount{_SAME_LINE_SPACE}*payable"
    rf"|invoice{_SAME_LINE_SPACE}*total"
    rf"|net{_SAME_LINE_SPACE}*payable|^[ \t]*total)"
    rf"{_SAME_LINE_SPACE}*[:.\-]?{_SAME_LINE_SPACE}*"
    rf"(?:INR|Rs\.?|₹)?{_SAME_LINE_SPACE}*{_AMOUNT}",
    re.IGNORECASE | re.MULTILINE,
)
_HSN_PATTERN = re.compile(r"\b(?:HSN|SAC)(?:\s*/\s*SAC)?\s*(?:code)?\s*[:.\-]?\s*(\d{4,8})\b",
                          re.IGNORECASE)

# The same label used as a *column header*, with the code printed on a later
# line underneath it rather than beside it.
#
# This is how nearly every real tax invoice carries HSN: rule 46 requires the
# code in the item table, and a table prints its heading once at the top. The
# inline pattern above cannot reach it, because the other column headings
# ("Qty", "Rate", "Amount") sit between the word and the digits. Left unread,
# every such invoice files with an empty HSN — a warning out of
# :func:`~app.services.filing.validate_invoice`, and a row missing from the
# rate-wise HSN summary the portal asks for in GSTR-1.
_HSN_HEADER = re.compile(r"\b(?:HSN|SAC)(?:\s*/\s*SAC)?(?:\s*code)?\b", re.IGNORECASE)

# A code as printed in that column. Either plain digits, or broken into groups
# by dots — "8482.10" is a common way to print the 6-digit code 848210.
#
# The lookarounds are what keep a money figure out. A comma or a further digit
# on either side disqualifies the run, so neither the "000" inside "10,000.00"
# nor the "11800" of "11800.00" can pass for a code; and the length check after
# normalising settles the rest, since the portal takes 4, 6 or 8 digits and
# nothing else.
_HSN_COLUMN_CODE = re.compile(r"(?<![\d,.])(\d{4}(?:\.\d{2}){1,2}|\d{4,8})(?![\d,.])")

# How far below its heading a column's first value may sit. A table puts it on
# the very next line; a couple more allows for a rule drawn under the headings,
# or a wrapped heading. Far enough past that and any digits found are another
# part of the document rather than this column's contents.
_HSN_COLUMN_REACH = 4


def _hsn_in_column(text: str) -> str | None:
    """An HSN read from the item table's column, or ``None``.

    Matched by horizontal position: the code has to overlap the columns the
    heading itself occupies. That is what tells it from the quantity and the
    rate printed alongside it, which are digits on the same line and are only
    ever distinguishable by which heading they sit under.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        header = _HSN_HEADER.search(line)
        if header is None:
            continue
        # Widened by a character at each end: a heading and its values are
        # often aligned to opposite edges of the column, so a short code under
        # a long heading can miss it by one.
        start, end = header.start() - 1, header.end() + 1
        for below in lines[index + 1 : index + 1 + _HSN_COLUMN_REACH]:
            for match in _HSN_COLUMN_CODE.finditer(below):
                if match.start() >= end or match.end() <= start:
                    continue
                code = match.group(1).replace(".", "")
                if len(code) in (4, 6, 8):
                    return code
    return None

# A figure carrying paise, which is the one shape that proves ``_AMOUNT``
# matched an amount in full rather than stopping part-way through one.
_COMPLETE_AMOUNT = re.compile(r"\d[\d,]*\.\d{2}")

# The rest of a grouping something broke with a space rather than a comma — the
# "000.00" of "1 000.00".
#
# It has to finish the figure and finish the line, because "a space and two or
# three digits" on its own is far commoner as the *next* thing printed than as
# the rest of this one. Matched loosely it read the page furniture below a
# total as the total's own missing thousands: "Grand Total: 100000" followed by
# a line beginning "18% GST included", or "22/09/2024", or "30 days credit" —
# every one of which put a whole, correctly-read figure through the discard
# below. That is this guard causing the failure it exists to prevent, from the
# other side, and on documents far commoner than the ones it rescues.
#
# So the run may not cross a newline: a thousands separator misread as a space
# is a space, never a line break. And it has to reach the end of its line,
# optionally through paise and a trailing currency word, so that the remainder
# of a figure ("1 000.00") is told apart from the start of the next column
# ("5000  25 items").
_SPACED_REMAINDER = re.compile(
    r"(?:[ \t]\d{2,3})+(?:\.\d{2})?[ \t]*(?:INR|Rs\.?|₹)?[ \t]*$",
    re.MULTILINE,
)


def _labelled_amount(pattern: re.Pattern[str], text: str) -> tuple[Decimal | None, str | None]:
    """The amount *pattern* labels, and the text it was read from.

    ``_AMOUNT`` spells a well-formed figure and stops at the first character
    that is not part of one — but stopping is not the same as failing, and what
    it hands back is a *prefix* rather than nothing. That is the same shape of
    bug as :data:`_EXPONENT_SUFFIX`, reached from the other side: there the
    mantissa of a number too wide to spell, here the front of a figure whose
    middle the page could not spell either.

    OCR is what produces them, constantly and in two ways. It reads a zero as
    the letter O — ``1,OOO.00`` — and the pattern takes ``1,`` and leaves the
    rest; and it reads a thousands comma as a space — ``1 000.00`` — and the
    pattern takes ``1``. Both then pass :func:`to_money`, which is asked
    whether the digits in hand are an amount and not whether they are the
    *whole* amount, so a ₹1,000 invoice stores one rupee.

    A tax head misread this way is at least survivable, because
    :func:`validate` foots the total against taxable value plus tax and says so
    when they disagree. These two fields are the ones that check is made *of*,
    and it only runs when both are non-zero — so a document printing a grand
    total and no taxable line, which is most receipts, stored ₹1 with no
    warning raised and no confidence lost. Nothing anywhere downstream
    re-derives it, and every screen then shows one rupee.

    So a figure is refused unless it was read whole. It counts as whole if it
    carries paise; failing that, it must not end mid-grouping on a comma, must
    not run straight into a letter or digit that the pattern could not take,
    and — when it has neither comma nor point to show it was ever grouped —
    must not be followed by a space and the rest of its own grouping.

    The caller gets the offending text back so it can say what was dropped,
    because an empty box is only better than a wrong one when someone can tell
    it was emptied on purpose.
    """
    match = pattern.search(text)
    if match is None:
        return None, None

    figure = match.group(1)
    tail = text[match.end():]
    whole = _COMPLETE_AMOUNT.fullmatch(figure) is not None
    truncated = (
        figure.endswith(",")
        or (not whole and tail[:1].isalnum())
        or (
            not whole
            and "," not in figure
            and _SPACED_REMAINDER.match(tail) is not None
        )
    )
    if truncated:
        # Enough of the line to show a reviewer what the page actually held.
        seen = text[match.start(1):match.start(1) + 24].splitlines()[0].strip()
        return None, seen
    return to_money(figure, default=None), figure
# "Whether the tax is payable on reverse charge basis" is required on the face
# of every tax invoice by rule 46(p), so the answer is printed on essentially
# all of them — and reading it backwards is expensive in both directions. A
# false yes moves the tax into GSTR-3B table 3.1(d) as a liability that must be
# settled in cash, takes the invoice's credit out of the pool, and on a *sale*
# prints ``rchrg: "Y"`` into the customer's GSTR-2B, telling them they owe tax
# the supplier has already charged. A false no leaves a real liability
# undeclared, with interest running from the due date.
#
# The label and the answer are therefore matched as separate things, because
# the words overlap. "Applicable" is an answer in "Reverse Charge: Applicable"
# and part of the *label* in "Reverse Charge Applicable: No" — and the previous
# pattern, which made the label word optional and then looked for an
# affirmative, could not tell them apart. Failing to match "No", it simply
# backtracked, gave the optional group up, and matched the label's own
# "Applicable" as the answer. So "Reverse Charge Applicable: No" — one of the
# commonest ways an Indian invoice prints this, along with "Whether Reverse
# Charge Applicable: No" — came back flagged reverse charge, which is precisely
# the reading :func:`to_flag` was written to stop and which survived here
# because the answer never reached it.
#
# The label parts are matched possessively, so they cannot be given back to be
# re-read as the answer. A label with no answer after it therefore matches
# nothing at all, which is the right outcome: an unanswered heading is not a
# declaration, and the whole module prefers an empty field a reviewer can see
# to a plausible wrong one.
#
# The answer itself is whatever word follows, negatives included, and
# :func:`to_flag` decides what it means — the same vocabulary that reads the
# model's answer and the portal's flags, rather than a third opinion here. That
# also picks up the affirmatives the old pattern could not reach: "Reverse
# Charge (Y/N): Y" required a separator it had no room for, so an invoice that
# genuinely was reverse charge read as one that was not.
#
# "RCM" is the other half of the vocabulary. It is not a rare abbreviation of
# the phrase — on a large share of invoices it is the *only* wording printed,
# because the label has to fit a box on a pre-printed form: "Tax payable under
# RCM: Yes", "RCM Applicable: No", "Whether tax is payable under RCM (Y/N): Y".
# None of those contain the words "reverse charge", so none of them matched, and
# every one of them came back ``False`` — the field's default, indistinguishable
# from an invoice that says the answer is no.
#
# A missed "yes" is the same error :func:`to_flag` exists to prevent, taken from
# the other side, and it costs more than the false positive does. Reverse charge
# means the recipient pays the tax, so an invoice wrongly read as ordinary is
# marked creditable — see :meth:`app.models.invoice.Invoice.creditable`, which
# is ``itc_eligible and not reverse_charge`` — and the business claims credit for
# tax it never paid and still owes. On a sale the same miss prints ``rchrg: "N"``
# into GSTR-1, telling the customer's GSTR-2B they need not account for it, so
# the liability is dropped by both parties at once.
#
# The answer is still required, so the acronym cannot fire on its own. That is
# what keeps a supplier with "RCM" in its trade name from flagging every invoice
# it issues: the word after it is the rest of the name, which is not an answer,
# and a label with no answer matches nothing here by design.
#
# The two spellings also appear together, because a form that has room for the
# phrase still glosses it: "Whether GST is payable under reverse charge (RCM):
# Yes". The bracket there sits exactly where the "(Y/N)" box does, so it is
# admitted in the same place — without it the label ends at "charge", the ")"
# is not a separator, and the answer standing right beside it is not read.
#
# "Mechanism" is the third spelling, and the commonest of the three on a form
# that spells anything out at all — it is the statutory name in sections 9(3)
# and 9(4), so "Reverse Charge Mechanism (RCM) Applicable: Yes" is at least as
# ordinary as the bare "Reverse Charge" this pattern was written against. Left
# out, the word sat between "charge" and everything after it — the bracket,
# the label words, the separator — so none of those matched what followed and
# the line matched nothing at all. That is the failure the acronym clause
# above already describes from the other direction: a real "Yes" went unread
# and the field kept its default of "no reverse charge", marking the invoice
# creditable and, on a sale, telling the buyer's GSTR-2B they owe nothing.
_REVERSE_CHARGE_PATTERN = re.compile(
    r"(?:reverse\s*charge|rcm)"
    r"(?:\s+mechanism)?"  # "Reverse Charge Mechanism"
    r"(?:\s*\(\s*(?:y\s*/\s*n|rcm|reverse\s*charge)\s*\))?+"  # "(Y/N)", "(RCM)"
    r"(?:\s+(?:is\s+)?applicable|\s+basis)?+"  # label words, never the answer
    r"\s*[:\-]?\s*"
    r"(not\s+applicable|n\s*/\s*a|yes|no|true|false|applicable|y|n)\b",
    re.IGNORECASE,
)


def _amount_on_line(line: str, *, after: int = 0) -> Decimal | None:
    """The monetary amount on a tax line, ignoring any rate printed on it.

    Invoices put the amount last — ``IGST @ 18%    81,000.00`` — so the last
    number wins, and percentages are removed first so an 18 cannot stand in
    for an 81,000.

    *after* narrows the search to the part of the line beyond a column, which
    is what lets one line carry two heads: see :func:`_tax_amounts_on_line`.
    A column with no number beyond it falls back to the whole line, because
    ``9,000.00 CGST`` prints the amount first and is still one head's figure.

    The cut happens *before* the percentages come out, and the order is the
    whole of it. ``after`` is an offset into the line the caller measured, and
    removing a rate shortens the line ahead of it: strip first and every column
    on the line slides left by as much text as the rates before it occupied,
    while ``after`` goes on pointing at where the label used to be. On
    ``CGST @ 6.00 % 1,111.11 SGST @ 6.00 % 2,222.22 CESS @ 12.00 % 3,333.33``
    that drift is ten characters by the time it reaches the cess column, enough
    to land inside the figure rather than before it — the cut fell after the
    ``3,`` and the head was read as ₹333.33 rather than ₹3,333.33, an order of
    magnitude of cess, silently, on a line that parses perfectly otherwise.

    The figure must be money-shaped and must not be part of a date — see
    :func:`_money_figures_in`. A head's label appears in prose and in page
    furniture that carry no amount at all, and the last number on such a line is
    a section number or half a date.
    """
    for candidate in (line[after:], line) if after else (line,):
        numbers = _money_figures_in(_PERCENT_PATTERN.sub(" ", candidate))
        if numbers:
            return to_money(numbers[-1], default=None)
    return None


def _tax_amounts_on_line(line: str) -> dict[str, Decimal]:
    """Which tax head each figure on one line belongs to.

    Tax is read a line at a time because the label, the rate and the amount sit
    on one line and only their order tells them apart. What that missed is that
    a line can name *two* heads, and the two ways it does are opposites.

    A line may lay the heads out side by side — ``CGST 9% 9,000.00  SGST 9%
    9,000.00`` — where each head has its own figure and both should be read.
    Reading each head from its own column is what makes that work; taking the
    last number on the line for both is right only by the accident that CGST
    and SGST are always equal.

    Or a line may *combine* them: ``Total Tax (CGST + SGST): 18,000.00``, the
    ordinary way an invoice summarises an intra-state supply. There is one
    figure and it is the total of both heads. Read per label, that ₹18,000
    became ₹18,000 of CGST *and* ₹18,000 of SGST — the tax on the invoice
    doubled, silently, at the moment of extraction.

    Doubled tax is not a display problem in either direction. On a purchase it
    doubles the credit claimed, which is over-claimed ITC with interest and a
    penalty on it. On a sale it doubles the output tax the business is told to
    pay. And it survives review, because every screen shows the same doubled
    figure and the arithmetic on the invoice is not re-derived anywhere a
    reviewer looks.

    The two are told apart by counting: as many figures as heads means a figure
    per head, and fewer means the figure is a combined one that belongs to no
    single head. A combined line is therefore left unread rather than split —
    the split would be a guess, and this module prefers an empty field a
    reviewer can see to a plausible wrong one. What it leaves behind is
    visible: ``validate_period`` reports the total against taxable value plus
    tax and says the figures do not foot.
    """
    found = [
        (match.start(), attr)
        for attr, label in _TAX_LABELS.items()
        if (match := label.search(line))
    ]
    if not found:
        return {}

    # Money-shaped figures only, on both sides of the count, and a date is not
    # one of them however it is punctuated. Counting every number instead let a
    # combined line reach the split it is meant to escape: ``Total Tax (CGST +
    # SGST) 18,000.00 as on 22/09/2024`` carries one amount and two heads, but
    # four numbers once the date is counted, so the guard saw enough to go
    # around and handed the combined ₹18,000 to SGST alone. The dotted form of
    # the same date makes up the shortfall by itself.
    stripped = _PERCENT_PATTERN.sub(" ", line)
    if len(_money_figures_in(stripped)) < len(found):
        return {}

    found.sort()
    amounts: dict[str, Decimal] = {}
    for index, (start, attr) in enumerate(found):
        # Up to the next head's label, so a column cannot reach past its own
        # into the neighbouring one's figure.
        end = found[index + 1][0] if index + 1 < len(found) else len(line)
        amount = _amount_on_line(line[:end], after=start)
        if amount is not None:
            amounts[attr] = amount
    return amounts


def _rate_on_line(line: str) -> Decimal | None:
    match = _PERCENT_PATTERN.search(line)
    return to_decimal(match.group(1), default=None) if match else None


def parse_heuristic(text: str) -> ParsedInvoice:
    """Extract what can be found by shape alone. Never raises."""
    result = ParsedInvoice(raw_text=text, parsed_with="heuristic")
    if not text:
        return result

    gstins = gstin_service.find_gstins(text)
    if gstins:
        # First GSTIN on an invoice is the issuer's, in the letterhead; the
        # buyer's appears lower, in the "Bill To" block.
        result.supplier_gstin = gstins[0]
        if len(gstins) > 1:
            result.buyer_gstin = gstins[1]

    result.invoice_number = _invoice_number_in(text)
    result.invoice_date = _invoice_date_in(text)
    if match := _HSN_PATTERN.search(text):
        result.hsn_code = match.group(1)
    else:
        # Only as a fallback: the inline label is the surer reading, and where
        # a document carries both it is the summary block at the foot that the
        # column repeats per line item.
        result.hsn_code = _hsn_in_column(text)

    # Tax amounts are read line by line, because the label, the rate and the
    # amount all sit on one line and only their order distinguishes them.
    rates: dict[str, Decimal] = {}
    for line in text.splitlines():
        amounts = _tax_amounts_on_line(line)
        for attr, label in _TAX_LABELS.items():
            if not label.search(line):
                continue
            amount = amounts.get(attr)
            if amount is not None and not getattr(result, attr):
                setattr(result, attr, amount)
            rate = _rate_on_line(line)
            if rate is not None and attr not in rates:
                rates[attr] = rate

    # Refused rather than half-read — see :func:`_labelled_amount`. The zero
    # left behind is said out loud, because this is the one field pair the
    # footing check in :func:`validate` is made of and it cannot report a
    # figure that was never stored.
    for attr, pattern in (("taxable_value", _TAXABLE_PATTERN), ("total_value", _TOTAL_PATTERN)):
        amount, seen = _labelled_amount(pattern, text)
        if amount is not None:
            setattr(result, attr, amount)
        elif seen is not None:
            result.warnings.append(
                f"Discarded a partly-read {attr.replace('_', ' ')}: {seen}"
            )

    # An 18% invoice is printed as 9% CGST + 9% SGST, so the invoice's rate is
    # the sum of the two halves — reporting 9 here would understate every
    # intra-state invoice by half.
    if "igst" in rates:
        result.tax_rate = normalize_rate(rates["igst"])
    elif "cgst" in rates:
        result.tax_rate = normalize_rate(rates["cgst"] + rates.get("sgst", rates["cgst"]))

    # The document's own answer, read by the same reader as the model's and the
    # portal's. ``bool()`` on the match is what this used to be, and it could
    # only ever say yes — see :data:`_REVERSE_CHARGE_PATTERN`.
    if match := _REVERSE_CHARGE_PATTERN.search(text):
        result.reverse_charge = to_flag(match.group(1))

    # Confidence here is coverage, not certainty: how many of the fields that
    # decide whether an invoice can be filed were actually found.
    found = sum(
        1
        for value in (
            result.supplier_gstin,
            result.invoice_number,
            result.invoice_date,
            result.total_value or None,
            result.taxable_value or None,
        )
        if value
    )
    # Capped: shape is not comprehension. Rounding is presentational — six
    # fields over five give 0, 0.12, 0.24, 0.36, 0.48, 0.6, every one of them
    # exact at two places already — so the mutation survivor on the precision
    # is an equivalent mutant, not an unasserted figure.
    result.confidence = round(found / 5 * 0.6, 2)
    return result


# --------------------------------------------------------------------------
# Model extractor
# --------------------------------------------------------------------------

def _text_messages(text: str) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Extract this GST invoice into exactly this JSON shape:\n{_EXTRACTION_SCHEMA}\n\n"
                f"INVOICE TEXT:\n{text[:12000]}"
            ),
        },
    ]


def _vision_messages(content: bytes, content_type: str) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Read this GST invoice image and extract it into exactly this "
                        f"JSON shape:\n{_EXTRACTION_SCHEMA}"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url(content, content_type)},
                },
            ],
        },
    ]


def _from_model_payload(payload: dict, text: str, model: str) -> ParsedInvoice:
    """Coerce a model's JSON into a :class:`ParsedInvoice`."""
    result = ParsedInvoice(raw_text=text, parsed_with=f"openrouter:{model}")

    result.supplier_name = _clean_str(payload.get("supplier_name"))
    result.buyer_name = _clean_str(payload.get("buyer_name"))
    result.invoice_number = _clean_str(payload.get("invoice_number"), 64)
    result.invoice_date = to_date(payload.get("invoice_date"))
    raw_hsn = payload.get("hsn_code")
    result.hsn_code = hsn_service.normalize_hsn_code(raw_hsn, cut_long=True)
    if result.hsn_code is None and str(raw_hsn if raw_hsn is not None else "").strip():
        # Dropped, not stored: the edit form would refuse it, and the GSTR-1
        # HSN summary would carry it. The reviewer is told what was read.
        result.warnings.append(f"Discarded an unreadable HSN/SAC code: {str(raw_hsn)[:20]}")
    result.reverse_charge = to_flag(payload.get("reverse_charge"))

    # A GSTIN is kept only if it checksums. The model is reading blurry text
    # and a plausible-looking 15-character string is the one field where a
    # confident wrong answer is worse than no answer: it silently attributes
    # the invoice to a different taxpayer.
    for key, attr in (("supplier_gstin", "supplier_gstin"), ("buyer_gstin", "buyer_gstin")):
        candidate = gstin_service.normalize(str(payload.get(key) or ""))
        if candidate and gstin_service.is_valid(candidate):
            setattr(result, attr, candidate)
        elif candidate:
            result.warnings.append(f"Discarded invalid {key.replace('_', ' ')}: {candidate}")

    for attr in ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value"):
        raw = payload.get(attr)
        amount = to_money(raw, default=None)
        if amount is None and str(raw if raw is not None else "").strip():
            # The model put something in this box and it is not an amount.
            # Said out loud, beside the zero it is being left as, because a
            # reviewer looking at a blank tax box needs to know the extractor
            # saw something there and refused it.
            #
            # Keyed on "was the field filled in" rather than on "did it parse
            # as a number", because the two most interesting refusals are not
            # numbers by the time they get here: ``"1E+100"`` is a mantissa the
            # number pattern cannot spell, and ``Infinity`` is not finite. A
            # guard asking ``to_decimal`` first fell silent on exactly those.
            #
            # The wording distinguishes the two, since they mean different
            # things to whoever reads the screen: a figure too large to be
            # money says the extraction found the right box and misread the
            # magnitude, and anything else says it did not find the box.
            kind = "out-of-range" if to_decimal(raw, default=None) is not None else "invalid"
            result.warnings.append(
                f"Discarded an {kind} {attr.replace('_', ' ')}: {str(raw)[:40]}"
            )
        setattr(result, attr, amount or Decimal("0.00"))
    result.tax_rate = normalize_rate(payload.get("tax_rate"))

    pos = _clean_str(payload.get("place_of_supply"), 2)
    if pos and pos.isdigit() and pos.zfill(2) in gstin_service.STATE_CODES:
        result.place_of_supply = pos.zfill(2)

    items = payload.get("line_items")
    if isinstance(items, list):
        result.line_items = [item for item in items if isinstance(item, dict)][:100]

    confidence = to_decimal(payload.get("confidence"), default=None)
    result.confidence = float(min(max(confidence or Decimal("0.7"), Decimal("0")), Decimal("1")))
    return result


def parse_with_model(
    *,
    text: str = "",
    content: bytes | None = None,
    content_type: str | None = None,
) -> ParsedInvoice:
    """Extract with an OpenRouter free model. Raises :class:`OpenRouterError`.

    Uses the vision model when given image bytes and the text model otherwise.
    """
    if content is not None:
        model = settings.openrouter_vision_model
        messages = _vision_messages(content, content_type or "image/jpeg")
    else:
        if not text.strip():
            raise OpenRouterError("No text to extract from")
        model = settings.openrouter_model
        messages = _text_messages(text)

    payload = chat_json(messages, model=model)
    return _from_model_payload(payload, text, model)


# --------------------------------------------------------------------------
# Combination and validation
# --------------------------------------------------------------------------

def _merge(primary: ParsedInvoice, secondary: ParsedInvoice) -> ParsedInvoice:
    """Fill *primary*'s empty fields from *secondary*, in place.

    Only ever fills gaps — a field the model answered is left alone, because
    the regex has no comprehension of layout and would happily overwrite the
    supplier's total with a line item's.
    """
    for attr in (
        "supplier_gstin", "supplier_name", "buyer_gstin", "buyer_name",
        "invoice_number", "invoice_date", "place_of_supply", "hsn_code", "tax_rate",
    ):
        if getattr(primary, attr) is None and getattr(secondary, attr) is not None:
            setattr(primary, attr, getattr(secondary, attr))
    for attr in ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value"):
        if not getattr(primary, attr) and getattr(secondary, attr):
            setattr(primary, attr, getattr(secondary, attr))
    return primary


def validate(parsed: ParsedInvoice) -> ParsedInvoice:
    """Append warnings for anything internally inconsistent, in place.

    These are the checks that catch a bad extraction before it reaches a
    return. Every one of them is a warning rather than a rejection: the user
    can see the invoice, and a number they can correct beats a document the
    product refused to accept.
    """
    # Extraction is the only door into this product that would take a negative
    # amount, and it took one silently.
    #
    # Every other door refuses it: ``InvoiceUpdate`` carries ``ge=0`` on all six
    # money fields, the review form refuses one before it is sent, and a
    # GSTR-2B states a credit note as positive figures with the sign carried by
    # ``document_type`` rather than by the money. ``apply_parsed`` writes what
    # the extractors produced straight onto the row, past all of that — so a
    # tax line reading ``IGST @ 18% -9,000.00`` stored igst = -9000.00 and the
    # dashboard reported input tax credit of *minus* nine thousand rupees, with
    # nothing on the invoice to say anything had happened.
    #
    # Both extractors reach it by ordinary means. ``_MONEY_FIGURE`` begins
    # ``-?``, so the heuristic reads the sign off a credit note or off a
    # discount line summarised under a tax head; ``to_money`` bounds a model's
    # magnitude but not its sign, so ``{"igst": -9000}`` is taken verbatim.
    #
    # Zeroed with the field named rather than kept, because a credit note is
    # not a thing this product models — there is no document type to carry the
    # sign, so a negative row is not a credit note that got in, it is an
    # invoice whose figures are wrong. The zero is a box a reviewer can see is
    # empty and the warning says which one and what it held, which is the trade
    # this module makes everywhere else. It also costs the extraction 0.1 of
    # confidence below, which is what routes the document to review.
    #
    # Done here, before the footing check reads these fields, so that check
    # reports the total against the figures actually stored.
    for attr in ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value"):
        amount = getattr(parsed, attr)
        if amount is not None and amount < 0:
            parsed.warnings.append(
                f"Discarded a negative {attr.replace('_', ' ')}: {amount}"
            )
            setattr(parsed, attr, Decimal("0.00"))

    if not parsed.supplier_gstin:
        parsed.warnings.append("No valid supplier GSTIN found")
    if not parsed.invoice_number:
        parsed.warnings.append("No invoice number found")
    if not parsed.invoice_date:
        parsed.warnings.append("No invoice date found")
    elif not gst_calendar.is_filable_invoice_date(parsed.invoice_date):
        # A warning rather than a discard, per this function's rule — but it
        # has to be *a* warning, because this field alone decides which return
        # the invoice appears in. A year misread out of a scan puts it in a
        # month no return covers, and it then leaves the register, the
        # dashboard and the GSTR-1 together, with nothing downstream left to
        # notice: every check there is scoped to a period, and the invoice is
        # no longer in one. The lowered confidence is what routes it to the
        # reviewer who can see the paper.
        parsed.warnings.append(
            f"Invoice date {parsed.invoice_date.isoformat()} is outside the span a "
            "GST invoice can fall in; check the year"
        )

    # Tolerance of ₹1: invoices round each tax line to the rupee, so a
    # correctly-extracted invoice routinely misses by a few paise.
    tolerance = Decimal("1.00")
    if parsed.taxable_value and parsed.total_value:
        expected = parsed.taxable_value + parsed.total_tax
        if abs(expected - parsed.total_value) > tolerance:
            parsed.warnings.append(
                f"Total {parsed.total_value} does not equal taxable value + tax ({expected})"
            )

    # Both an intra-state and an inter-state split on one invoice is
    # impossible under GST — it means the extractor read a summary table wrong.
    if parsed.igst and (parsed.cgst or parsed.sgst):
        parsed.warnings.append("Invoice carries both IGST and CGST/SGST")

    if parsed.cgst and parsed.sgst and parsed.cgst != parsed.sgst:
        parsed.warnings.append(f"CGST {parsed.cgst} and SGST {parsed.sgst} should be equal")

    # Both GSTINs, because a split can only be called wrong against a border,
    # and one party's state does not locate a border. The guard is a shortcut
    # rather than the decision: `is_interstate` answers None when either side
    # is missing or unreadable, and neither branch below fires on None — which
    # is why relaxing this `and` to `or` survives mutation. Kept because the
    # cheap read should not depend on the expensive one staying careful.
    if parsed.supplier_gstin and parsed.buyer_gstin:
        interstate = gstin_service.is_interstate(parsed.supplier_gstin, parsed.buyer_gstin)
        if interstate is True and not parsed.igst and parsed.total_tax:
            parsed.warnings.append("Inter-state supply taxed as CGST/SGST instead of IGST")
        elif interstate is False and parsed.igst:
            parsed.warnings.append("Intra-state supply taxed as IGST instead of CGST/SGST")

    if parsed.warnings:
        # Each unresolved inconsistency is a reason to trust the whole
        # extraction less, which is what routes an invoice to human review.
        parsed.confidence = round(max(0.0, parsed.confidence - 0.1 * len(parsed.warnings)), 2)
    return parsed


PASSWORD_PROTECTED_WARNING = (
    "This PDF is password-protected, so it could not be read. Open it, save or "
    "print it as a new PDF without the password, and upload that instead."
)


def parse_invoice(
    *,
    content: bytes | None = None,
    content_type: str | None = None,
    filename: str | None = None,
    text: str | None = None,
) -> ParsedInvoice:
    """Extract an invoice from an upload, whatever form it arrived in.

    Never raises. Falls back through model → OCR → heuristics so that an
    upload always produces a row: an invoice the user can correct is worth far
    more than a failed request, since the paper is usually back in a file by
    the time they see the error.
    """
    body = text or ""
    if not body and content is not None:
        body = document_text.extract(content, content_type, filename)

    is_pdf = (content_type or "").lower() == "application/pdf" or (
        filename or ""
    ).lower().endswith(".pdf")
    if not body and content is not None and is_pdf and document_text.is_password_protected(
        content
    ):
        # Nothing downstream can read it: sent on, it cost a vision call on a
        # file the model cannot render, then an OCR pass on bytes that are not
        # an image, and the review screen blamed "no AI model was available".
        # Say what is actually wrong, and what to do about it.
        logger.info("PDF is password-protected; not read", extra={"upload_filename": filename})
        locked = parse_heuristic("")
        locked.warnings.append(PASSWORD_PROTECTED_WARNING)
        return validate(locked)

    treat_as_image = content is not None and not body and (
        document_text.is_image(content_type, filename)
        or (content_type or "").lower() == "application/pdf"
    )

    parsed: ParsedInvoice | None = None
    if is_configured():
        try:
            if treat_as_image:
                # A PDF that yielded no text is a scan; the vision model reads
                # images, so hand it the file and let it render.
                parsed = parse_with_model(
                    content=content, content_type=content_type or "image/jpeg"
                )
            elif body:
                parsed = parse_with_model(text=body)
        except OpenRouterError as exc:
            logger.warning(
                "Model extraction failed, falling back: %s", exc,
                extra={"content_type": content_type, "model": settings.openrouter_model},
            )

    if parsed is None and treat_as_image and content is not None:
        # No model, or the model failed: OCR the image so the heuristics have
        # something to read.
        ocr_text = document_text.ocr_image(content)
        if ocr_text:
            body = ocr_text
            if is_configured():
                try:
                    parsed = parse_with_model(text=body)
                    parsed.parsed_with = f"tesseract+{parsed.parsed_with}"
                except OpenRouterError as exc:
                    logger.warning(
                        "Model extraction after OCR failed: %s", exc,
                        extra={"content_type": content_type, "model": settings.openrouter_model},
                    )

    heuristic = parse_heuristic(body)
    if parsed is None:
        parsed = heuristic
        if not body:
            parsed.warnings.append(
                "No text could be read from this file and no AI model was available"
            )
    else:
        parsed.raw_text = body
        _merge(parsed, heuristic)

    return validate(parsed)
