"""The free GST tools as an API a ChatGPT Custom GPT can call (GPT Actions).

Public, unauthenticated and stateless: no route here reads or writes a tenant
row. Each one is a thin wrapper over a service the web tools already use, so a
GST rule changes in one place and the GPT follows it. The spec a GPT imports is
``app/gpt/openapi.yaml``, served below, and ``tests/test_gpt_actions.py``
holds it to the routes that actually exist.

Rate limited per address under one bucket, ``gpt_actions``, and generously:
ChatGPT calls arrive from OpenAI's egress addresses, so every user of every
GPT built on this shares a handful of IPs. Retune it through
``RATE_LIMIT_OVERRIDES`` rather than a deploy if real traffic meets it.

Answers are shaped to be *read aloud by a model*: every amount is a decimal
string, every state code comes with its name, and a disclaimer travels with
anything a taxpayer might act on.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path as FilePath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.core.config import settings
from app.core.rate_limit import RateLimit
from app.models.mixins import MONEY_MAX
from app.schemas.gpt import GSTIN_INPUT_MAX, STATE_CODE_PATTERN, InvoiceRequest
from app.services import filing_dates, gst_calendar, hsn, jev_service
from app.services import gst_calculator as calc
from app.services import gstin as gstin_service

router = APIRouter(prefix="/gpt", tags=["gpt"])

_gpt_limit = RateLimit("gpt_actions", "600/minute", by="ip")

SITE = settings.public_site_url
_SPEC_FILE = FilePath(__file__).resolve().parent.parent / "gpt" / "openapi.yaml"

DISCLAIMER = (
    "Computed by DoAide GST from published rules; not legal or tax advice. "
    "Confirm with a CA or the GST portal before filing."
)


# ``+ 0`` drops the sign of a negative zero. ``-0`` passes every ``ge=0``
# bound and compares equal to the 0% slab, and a ``-0.00`` CGST is not a
# figure anyone can copy onto an invoice.
def _money(value: Decimal) -> str:
    return f"{value + 0:.2f}"


def _rate(value: Decimal) -> str:
    return f"{(value + 0).normalize():f}"


def _split(tax: calc.TaxSplit) -> dict[str, Any]:
    return {
        "taxable_value": _money(tax.taxable_value),
        "gst_rate": _rate(tax.rate),
        "cgst": _money(tax.cgst),
        "sgst": _money(tax.sgst),
        "igst": _money(tax.igst),
        "total_tax": _money(tax.total_tax),
        "total": _money(tax.total),
    }


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _state(code: str) -> dict[str, str]:
    return {"code": code, "name": gstin_service.STATE_CODES[code]}


# ---------------------------------------------------------------------------
# GSTIN
# ---------------------------------------------------------------------------


@router.get(
    "/gstin/{gstin}",
    operation_id="validateGstin",
    summary="Validate and decode a GSTIN",
    description=(
        "Checks a GSTIN's format and check digit and decodes the state, PAN and "
        "entity type it encodes. Offline validation — it does not query the GST "
        "portal for registration status or legal name.\n\n"
        'Always 200 for anything GSTIN-sized: an invalid one is `{"valid": false, '
        '"error": ...}`, which a model can explain, rather than an error status.'
    ),
    dependencies=[Depends(_gpt_limit)],
)
def validate_gstin(gstin: str = Path(max_length=GSTIN_INPUT_MAX)) -> dict[str, Any]:
    try:
        parts = gstin_service.parse(gstin)
    except gstin_service.InvalidGSTIN as exc:
        return {"gstin": gstin_service.normalize(gstin), "valid": False, "error": str(exc)}
    return {
        "gstin": parts.gstin,
        "valid": True,
        "state": _state(parts.state_code),
        "pan": parts.pan,
        "entity_type": gstin_service.entity_type(parts.pan),
        "registration_number_in_state": parts.entity_number,
        "note": (
            "Format and checksum are valid. Active/cancelled status and legal name "
            "can only be confirmed on the GST portal (services.gst.gov.in)."
        ),
        "lookup_url": f"{SITE}/lookup",
    }


# ---------------------------------------------------------------------------
# HSN
# ---------------------------------------------------------------------------


@router.get(
    "/hsn",
    operation_id="searchHsn",
    summary="Search HSN codes and their GST rates",
    description=(
        "Searches HSN codes by product name, description words or a code "
        "prefix (e.g. `rice`, `mobile phone`, `8517`) and returns each match "
        "with its GST rate."
    ),
    dependencies=[Depends(_gpt_limit)],
)
def search_hsn(
    q: str = Query(
        min_length=1, max_length=100, description="Product name, keywords, or HSN code prefix.",
    ),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    results = hsn.search(q, limit=limit)
    alias = hsn.find_product(q)
    best = None
    if alias is not None:
        entry = hsn.by_code(alias.hsn)
        best = {
            "product": alias.product,
            "hsn_code": alias.hsn,
            "gst_rate": _rate(alias.rate),
            "description": entry.description if entry else None,
        }
        # A product alias names the right heading even when the tariff wording
        # shares no word with the query ("atta" is "wheat or meslin flour"),
        # so its row leads the list rather than being absent from it.
        if entry is not None and entry not in results:
            results = [entry, *results][:limit]
    # Nothing in the table matched the words, so ask Jev which chapter the
    # description belongs to and point the caller there. Only on a miss: a
    # table hit is an exact tariff heading and outranks a model's guess.
    suggestion = None
    if not results and best is None:
        chapter = jev_service.classify_hsn_chapter(q)
        if chapter is not None:
            suggestion = {
                "chapter": chapter.label,
                "heading": jev_service.hsn_chapters()[chapter.label],
                "confidence": round(chapter.confidence, 4),
                "browse_query": chapter.label,
            }
    return {
        "query": q,
        "best_match": best,
        **({"suggested_chapter": suggestion} if suggestion else {}),
        "results": [
            {
                "hsn_code": e.code,
                "code_type": "SAC" if e.sac else "HSN",
                "description": e.description,
                "category": e.category,
                "gst_rate": _rate(e.rate),
            }
            for e in results
        ],
        "count": len(results),
        "note": (
            "Rates follow GST 2.0 slabs (0/5/18/40%, plus 0.25% and 3% for "
            "specific goods). The 8-digit tariff line can change the rate; "
            "check the CBIC schedule for edge cases."
        ),
        "browse_url": f"{SITE}/hsn",
    }


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


@router.get(
    "/calculate",
    operation_id="calculateGst",
    summary="Calculate GST on an amount",
    description=(
        "Adds GST to a price (`exclusive`) or backs it out of a GST-inclusive "
        "price (`inclusive`), split into CGST+SGST for an intra-state supply or "
        "IGST for an inter-state one. Pass both state codes to have the supply "
        "type decided from them."
    ),
    dependencies=[Depends(_gpt_limit)],
)
def calculate(
    amount: Decimal = Query(ge=0, le=MONEY_MAX, description="Amount in rupees."),
    rate: Decimal = Query(ge=0, le=40, description="GST rate in percent, e.g. 18."),
    mode: str = Query(default="exclusive", pattern=r"^(exclusive|inclusive)$"),
    supply_type: str = Query(default="intra_state", pattern=r"^(intra_state|inter_state)$"),
    supplier_state_code: str | None = Query(default=None, pattern=STATE_CODE_PATTERN),
    buyer_state_code: str | None = Query(default=None, pattern=STATE_CODE_PATTERN),
) -> dict[str, Any]:
    try:
        calc.check_rate(rate)
        supplier = calc.resolve_state(None, supplier_state_code, who="Supplier")
        buyer = calc.resolve_state(None, buyer_state_code, who="Buyer")
    except calc.GstInputError as exc:
        raise _unprocessable(exc) from None

    # State codes, when both are known, outrank ``supply_type``: the split is
    # decided by where the parties are, not by what the caller believed it was.
    interstate = supplier != buyer if supplier and buyer else supply_type == "inter_state"
    compute = calc.from_inclusive if mode == "inclusive" else calc.on_taxable
    split = compute(amount, rate, interstate=interstate)
    return {
        "mode": mode,
        "supply_type": "inter_state" if interstate else "intra_state",
        "input_amount": _money(calc.q(amount)),
        **_split(split),
        "calculator_url": f"{SITE}/calculator",
    }


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


@router.post(
    "/invoice",
    operation_id="generateInvoice",
    summary="Generate GST invoice data",
    description=(
        "Computes a complete GST tax invoice — line amounts, discounts, "
        "CGST/SGST or IGST by place of supply, a rate-wise tax summary, round "
        "off and the amount in words. Returns structured data, not a file; "
        "nothing is stored."
    ),
    dependencies=[Depends(_gpt_limit)],
)
def generate_invoice(body: InvoiceRequest) -> dict[str, Any]:
    try:
        seller_state = calc.resolve_state(body.seller.gstin, body.seller.state_code, who="Seller")
        buyer_state = calc.resolve_state(body.buyer.gstin, body.buyer.state_code, who="Buyer")
        pos = calc.resolve_state(None, body.place_of_supply, who="Place of supply") or buyer_state
        if seller_state is None:
            raise calc.GstInputError("Seller needs a GSTIN or a state code to decide the tax split")
        if pos is None:
            raise calc.GstInputError(
                "Give the buyer's GSTIN or state code, or a place of supply, "
                "to decide the tax split"
            )
        invoice_date = body.invoice_date or gst_calendar.today_ist()
        # A date outside the periods GST returns cover is a slipped year, not
        # an invoice: nothing before July 2017 carried GST.
        if not gst_calendar.is_period(gst_calendar.period_of(invoice_date)):
            raise calc.GstInputError(
                f"Invoice date {invoice_date.isoformat()} is outside GST: use a date "
                f"from {gst_calendar.FIRST_PERIOD} to {gst_calendar.LAST_PERIOD}"
            )
        invoice = calc.build_invoice(
            [
                calc.LineInput(
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    gst_rate=item.gst_rate,
                    hsn_code=item.hsn_code,
                    unit=item.unit,
                    discount_percent=item.discount_percent,
                )
                for item in body.items
            ],
            supplier_state=seller_state,
            place_of_supply=pos,
            invoice_date=invoice_date,
            round_to_rupee=body.round_off,
        )
    except calc.GstInputError as exc:
        raise _unprocessable(exc) from None

    def party(p, state: str | None) -> dict[str, Any]:
        return {
            "name": p.name,
            "gstin": gstin_service.normalize(p.gstin) if p.gstin else None,
            "state": _state(state) if state else None,
            "address": p.address,
        }

    warnings = []
    if not body.buyer.gstin:
        warnings.append(
            "No buyer GSTIN: this is a B2C invoice and the buyer cannot claim ITC on it."
        )
    missing_hsn = [line.number for line in invoice.lines if not line.item.hsn_code]
    if missing_hsn:
        which = (
            f"Line {missing_hsn[0]} has" if len(missing_hsn) == 1
            else f"Lines {', '.join(map(str, missing_hsn))} have"
        )
        warnings.append(
            f"{which} no HSN/SAC code. It is mandatory "
            "on B2B tax invoices: 4 digits up to ₹5 crore turnover, 6 digits above."
        )

    return {
        "invoice_number": body.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat(),
        "seller": party(body.seller, seller_state),
        "buyer": party(body.buyer, buyer_state),
        "place_of_supply": _state(invoice.place_of_supply),
        "supply_type": "inter_state" if invoice.interstate else "intra_state",
        "reverse_charge": False,
        "items": [
            {
                "line": line.number,
                "description": line.item.description,
                "hsn_code": line.item.hsn_code,
                "quantity": f"{line.item.quantity.normalize():f}",
                "unit": line.item.unit,
                "unit_price": _money(line.item.unit_price),
                "gross_amount": _money(line.gross),
                "discount_percent": _rate(line.item.discount_percent),
                "discount": _money(line.discount),
                **_split(line.tax),
            }
            for line in invoice.lines
        ],
        "tax_summary": [_split(s) for s in invoice.rate_summary],
        "totals": {
            "taxable_value": _money(invoice.taxable_value),
            "cgst": _money(invoice.cgst),
            "sgst": _money(invoice.sgst),
            "igst": _money(invoice.igst),
            "total_tax": _money(invoice.total_tax),
            "round_off": _money(invoice.round_off),
            "grand_total": _money(invoice.grand_total),
        },
        "amount_in_words": calc.amount_in_words(invoice.grand_total),
        "notes": body.notes,
        "warnings": warnings,
        "pdf_tool_url": f"{SITE}/invoice-generator",
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Filing dates
# ---------------------------------------------------------------------------


@router.get(
    "/filing-dates",
    operation_id="getFilingDates",
    summary="GST return due dates for a period",
    description=(
        "Lists the returns due for a tax period (default: last month) for a "
        "monthly, quarterly (QRMP) or composition filer, with the due date, "
        "days remaining, and the late fee accrued so far if overdue."
    ),
    dependencies=[Depends(_gpt_limit)],
)
def filing_dates_for(
    period: str | None = Query(
        default=None, pattern=gst_calendar.PERIOD_PATTERN,
        description="Tax period as YYYY-MM. Defaults to the month before today.",
    ),
    filer_type: filing_dates.FilerType = Query(default=filing_dates.FilerType.MONTHLY),
    state_code: str | None = Query(
        default=None, pattern=STATE_CODE_PATTERN,
        description="Two-digit state code; decides the QRMP GSTR-3B date (22nd or 24th).",
    ),
    previous_year_turnover: Decimal | None = Query(
        default=None, ge=0, le=MONEY_MAX,
        description="Last year's aggregate turnover in rupees; sets the late-fee cap.",
    ),
    as_of: date | None = Query(
        default=None, description="Date to measure from (YYYY-MM-DD). Defaults to today in India.",
    ),
) -> dict[str, Any]:
    if state_code is not None and state_code not in gstin_service.STATE_CODES:
        raise _unprocessable(ValueError(f"{state_code!r} is not a GST state code"))
    today = as_of or gst_calendar.today_ist()
    if period is None:
        period = gst_calendar.previous_period(gst_calendar.period_of(today))
        # The month before July 2017 has no return; asking "as of" a date
        # that early is answered for GST's first month instead of a 500. One
        # past the far end is refused: answering it for July 2017 instead
        # would be a confident date for the wrong decade.
        if not gst_calendar.is_period(period):
            if period > gst_calendar.LAST_PERIOD:
                raise _unprocessable(ValueError(
                    f"as_of {today.isoformat()} is past the last GST period "
                    f"this answers for ({gst_calendar.LAST_PERIOD})"
                ))
            period = gst_calendar.FIRST_PERIOD

    statuses = [
        filing_dates.status_of(d, today, previous_year_turnover)
        for d in filing_dates.deadlines(period, filer_type, state_code)
    ]
    return {
        "period": period,
        "financial_year": filing_dates.financial_year_label(period),
        "filer_type": filer_type.value,
        "state": _state(state_code) if state_code else None,
        "as_of": today.isoformat(),
        "deadlines": [
            {
                "form": s.deadline.form,
                "description": s.deadline.description,
                "covers": s.deadline.covers,
                "due_date": s.deadline.due.isoformat(),
                "days_remaining": s.days_remaining,
                "status": s.status,
                "optional": s.deadline.optional,
                **(
                    {
                        "late_fee_so_far": _money(s.late_fee),
                        "nil_return_late_fee_so_far": _money(s.nil_late_fee),
                    }
                    if s.late_fee is not None and s.nil_late_fee is not None
                    else {}
                ),
            }
            for s in statuses
        ],
        "late_fee_rules": (
            "GSTR-1/GSTR-3B: ₹50/day (₹20/day for nil returns), capped by turnover "
            "(₹2,000 up to ₹1.5 cr, ₹5,000 up to ₹5 cr, ₹10,000 above; ₹500 for "
            "nil). Interest on unpaid tax is 18% p.a. extra. Without a turnover "
            "the highest cap is assumed."
        ),
        "note": (
            "Statutory dates without notified extensions — the government "
            "sometimes extends a deadline days before it falls."
        ),
        "calendar_url": f"{SITE}/due-dates",
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Spec and privacy statement, for the GPT builder
# ---------------------------------------------------------------------------


@router.get(
    "/openapi.yaml",
    summary="OpenAPI spec for GPT Actions",
    description="The spec to import in the GPT builder (Actions → Import from URL).",
    response_class=PlainTextResponse,
    dependencies=[Depends(_gpt_limit)],
)
def openapi_spec() -> PlainTextResponse:
    # The file names the production origin; a deployment elsewhere serves its own.
    spec = _SPEC_FILE.read_text(encoding="utf-8").replace("https://gst.doaide.com", SITE)
    return PlainTextResponse(spec, media_type="application/yaml")


PRIVACY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>DoAide GST — GPT Actions privacy</title></head>
<body>
<h1>DoAide GST GPT Actions — Privacy Policy</h1>
<p>The DoAide GST actions used by ChatGPT (GSTIN validation, HSN search, GST
calculation, invoice data and filing dates) are stateless calculators.</p>
<ul>
<li>No account is needed and none is created.</li>
<li>Request contents (GSTINs, amounts, invoice details) are used only to compute
the response and are not stored, sold or shared.</li>
<li>Standard access logs (time, path, status, a truncated network address) are
kept for up to 30 days for security and rate limiting. Request bodies are not
logged.</li>
<li>Results are informational and not legal or tax advice.</li>
</ul>
<p>Contact: <a href="{SITE}">{HOST}</a></p>
</body></html>
""".replace("{SITE}", SITE).replace("{HOST}", settings.public_site_host)


@router.get(
    "/privacy",
    summary="Privacy policy for the GPT Actions",
    description="The privacy policy URL a public GPT with Actions must link.",
    response_class=HTMLResponse,
    dependencies=[Depends(_gpt_limit)],
)
def privacy() -> HTMLResponse:
    return HTMLResponse(PRIVACY_HTML)
