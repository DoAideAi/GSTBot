"""GST on an amount, and on a whole invoice, for the public tools.

No row is read and none is written: this is arithmetic over what the caller
sent. It sits beside the tenant-side services rather than inside them because
those work from stored invoices and this works from a form.

Two rules shape every figure here:

* **Heads are computed, not halved.** On an intra-state supply CGST and SGST
  are each ``rate / 2`` of the taxable value, rounded on their own. Halving a
  rounded total instead leaves an odd paisa that has to go to one head, and
  the portal refuses a CGST that differs from its SGST.
* **An inclusive price is honoured to the paisa.** Backing tax out of a gross
  figure computes the tax heads first and makes the taxable value whatever is
  left, so taxable + tax always equals the number the user typed. Computing
  the taxable value first and taxing it can land a paisa either side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.models.mixins import ZERO
from app.services import gstin as gstin_service
from app.services.invoice_parser import VALID_TAX_RATES

# Every rate a supply can carry today, plus the 12% and 28% slabs GST 2.0
# folded away in September 2025 — invoices dated before then still use them,
# and someone checking an old bill is a real caller. A rate outside this set is
# a typo (1.8 for 18) far more often than a rate, so it is refused rather than
# computed.
#
# The parser's list, not a copy of it. This module kept its own, and it had
# lost 1%: the calculator and the GPT invoice tool answered "1% is not a GST
# rate" for a rate the parser reads, the invoice editor accepts and filing
# files. The parser's own comment records the same drift once before.
VALID_RATES = frozenset(VALID_TAX_RATES)

HUNDRED = Decimal("100")
PAISA = Decimal("0.01")


class GstInputError(ValueError):
    """The request is well-formed but asks for something that is not GST."""


def q(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def check_rate(rate: Decimal) -> Decimal:
    if rate not in VALID_RATES:
        allowed = ", ".join(f"{r.normalize():f}" for r in sorted(VALID_RATES))
        raise GstInputError(f"{quoted_rate(rate)}% is not a GST rate. Use one of: {allowed}")
    return rate


def quoted_rate(rate: Decimal) -> str:
    """The refused rate as the caller would recognise it.

    Positional notation spells ``1E-999999`` as a million characters, which
    the error handler then cut to its ceiling — so the sentence saying which
    rates are allowed never arrived, and each such request built a megabyte of
    zeros to throw away. Past a dozen digits either side, the caller sent it in
    exponent form and gets it back that way.
    """
    normalized = rate.normalize()
    return f"{normalized:f}" if abs(normalized.adjusted()) <= 12 else f"{normalized:E}"


# ``frozen=True`` on this and the two input records below survives mutation:
# nothing in the application assigns to one, so frozen and unfrozen behave
# alike. It is kept for what it rules out, not for anything a test observes.
@dataclass(frozen=True)
class TaxSplit:
    taxable_value: Decimal
    rate: Decimal
    interstate: bool
    cgst: Decimal
    sgst: Decimal
    igst: Decimal

    @property
    def total_tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst

    @property
    def total(self) -> Decimal:
        return self.taxable_value + self.total_tax


def on_taxable(taxable: Decimal, rate: Decimal, *, interstate: bool) -> TaxSplit:
    """Tax added on top of a taxable value."""
    taxable = q(taxable)
    if interstate:
        return TaxSplit(taxable, rate, True, ZERO, ZERO, q(taxable * rate / HUNDRED))
    head = q(taxable * rate / (2 * HUNDRED))
    return TaxSplit(taxable, rate, False, head, head, ZERO)


def from_inclusive(gross: Decimal, rate: Decimal, *, interstate: bool) -> TaxSplit:
    """Tax backed out of a price that already includes it."""
    gross = q(gross)
    if interstate:
        igst = q(gross * rate / (HUNDRED + rate))
        return TaxSplit(gross - igst, rate, True, ZERO, ZERO, igst)
    head = q(gross * rate / (2 * (HUNDRED + rate)))
    return TaxSplit(gross - 2 * head, rate, False, head, head, ZERO)


# ---------------------------------------------------------------------------
# Parties and place of supply
# ---------------------------------------------------------------------------


def resolve_state(gstin: str | None, state_code: str | None, *, who: str) -> str | None:
    """The state a party is in, from its GSTIN or an explicit code.

    Both given and disagreeing is refused rather than one silently winning:
    the tax split turns on this, and a GSTIN from Karnataka with a state code
    for Maharashtra is a form filled in wrong, not a preference.
    """
    from_gstin = None
    if gstin:
        try:
            from_gstin = gstin_service.parse(gstin).state_code
        except gstin_service.InvalidGSTIN as exc:
            raise GstInputError(f"{who} GSTIN is invalid: {exc}") from None
    if state_code is not None and state_code not in gstin_service.STATE_CODES:
        raise GstInputError(f"{who} state code {state_code!r} is not a GST state code")
    if from_gstin and state_code and from_gstin != state_code:
        raise GstInputError(
            f"{who} GSTIN is registered in state {from_gstin} but state code {state_code} was given"
        )
    return from_gstin or state_code


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineInput:
    description: str
    quantity: Decimal
    unit_price: Decimal
    gst_rate: Decimal
    hsn_code: str | None = None
    unit: str | None = None
    discount_percent: Decimal = ZERO


@dataclass(frozen=True)
class Line:
    number: int
    item: LineInput
    gross: Decimal
    discount: Decimal
    tax: TaxSplit


@dataclass
class Invoice:
    supplier_state: str
    place_of_supply: str
    interstate: bool
    lines: list[Line]
    invoice_date: date
    taxable_value: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO
    rate_summary: list[TaxSplit] = field(default_factory=list)

    @property
    def total_tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst


def build_invoice(
    items: list[LineInput],
    *,
    supplier_state: str,
    place_of_supply: str,
    invoice_date: date,
    round_to_rupee: bool = True,
) -> Invoice:
    interstate = supplier_state != place_of_supply
    lines: list[Line] = []
    for number, item in enumerate(items, start=1):
        check_rate(item.gst_rate)
        gross = q(item.quantity * item.unit_price)
        discount = q(gross * item.discount_percent / HUNDRED)
        lines.append(
            Line(number, item, gross, discount,
                 on_taxable(gross - discount, item.gst_rate, interstate=interstate))
        )

    invoice = Invoice(supplier_state, place_of_supply, interstate, lines, invoice_date)
    for line in lines:
        invoice.taxable_value += line.tax.taxable_value
        invoice.cgst += line.tax.cgst
        invoice.sgst += line.tax.sgst
        invoice.igst += line.tax.igst

    # One row per rate, the way GSTR-1's rate-wise table and every printed tax
    # summary present it. Summed from the lines rather than recomputed on the
    # rate's total taxable value, so the summary agrees with the lines above it
    # to the paisa — recomputing would round once instead of per line.
    by_rate: dict[Decimal, list[TaxSplit]] = {}
    for line in lines:
        by_rate.setdefault(line.tax.rate, []).append(line.tax)
    invoice.rate_summary = [
        TaxSplit(
            sum((s.taxable_value for s in splits), ZERO), rate, interstate,
            sum((s.cgst for s in splits), ZERO),
            sum((s.sgst for s in splits), ZERO),
            sum((s.igst for s in splits), ZERO),
        )
        for rate, splits in sorted(by_rate.items())
    ]

    exact = invoice.taxable_value + invoice.total_tax
    if round_to_rupee:
        invoice.grand_total = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(PAISA)
    else:
        invoice.grand_total = exact
    invoice.round_off = invoice.grand_total - exact
    return invoice


# ---------------------------------------------------------------------------
# Amount in words, Indian numbering
# ---------------------------------------------------------------------------

_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return f"{_TENS[n // 10]} {_ONES[n % 10]}".strip()


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def _integer_words(n: int) -> str:
    """*n* in words, grouped crore / lakh / thousand as an Indian invoice prints it.

    Crores are not capped at 99: the remaining quotient is spelled out
    recursively ("One Thousand Crore"), which is how a ₹1,000 crore figure is
    read aloud.
    """
    if n == 0:
        return "Zero"
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    parts = []
    if crore:
        parts.append(f"{_integer_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    amount = q(amount)
    rupees = int(amount)
    # ``* 101`` survives mutation, and cannot be told apart: *amount* is
    # already whole paise, so the fraction is k/100 for k < 100, and k/100 * 101
    # is k + k/100 — which ``int`` truncates back to k for every k there is.
    paise = int((amount - rupees) * 100)
    words = f"Rupees {_integer_words(rupees)}"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return f"{words} Only"
