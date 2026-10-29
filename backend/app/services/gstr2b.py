"""Reading a GSTR-2B into something reconcilable.

GSTR-2B is the static ITC statement the portal generates for a buyer on the
14th of each month. It is the authoritative answer to "what have my suppliers
actually declared about me", and it is the right-hand side of every match this
product makes.

Two shapes arrive in practice and both are supported:

* **The portal JSON.** Downloaded from Returns > GSTR-2B > Download. The real
  envelope is ``{"data": {"docdata": {"b2b": [...]}}}``, with a supplier-level
  wrapper (``ctin``, ``trdnm``, ``supfildt``) holding a list of invoices, each
  holding a list of rate-wise ``items``. Abbreviated keys throughout.
* **The CSV/Excel export.** One flat row per rate line, with human column
  headings. Businesses forward this far more often than the JSON because it is
  what opens in Excel.

Everything is flattened to one :class:`GSTR2BRecord` per *invoice* — rate-wise
items are summed — because an invoice is the unit a buyer books, disputes and
claims credit on. The rate breakdown is kept on the record for display.

Nothing here touches the database: this module turns bytes into records, and
:mod:`app.services.reconciliation` decides what they mean.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.core.sanitize import encodable
from app.models.mixins import MONEY_MAX
from app.services import gst_calendar
from app.services import gstin as gstin_service
from app.services.invoice_parser import to_date, to_decimal, to_flag, to_money

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


class GSTR2BParseError(ValueError):
    """The uploaded file is not a GSTR-2B we can read."""


@dataclass
class GSTR2BRecord:
    """One invoice as the supplier declared it, normalised.

    ``itc_available`` carries the portal's ``itcavl`` flag: the supplier filed
    the invoice, but the portal may still mark the credit unavailable (a
    time-barred invoice, or a place of supply that makes it ineligible). A
    record can therefore be matched and still yield no credit, which is a
    different conversation with the supplier than a missing invoice.
    """

    supplier_gstin: str | None = None
    supplier_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    period: str | None = None
    place_of_supply: str | None = None

    taxable_value: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO
    cess: Decimal = ZERO
    total_value: Decimal = ZERO

    itc_available: bool = True
    reverse_charge: bool = False
    # "R" regular, "C" credit note, "D" debit note, "ISD", "IMPG"...
    document_type: str = "R"
    supplier_filing_date: date | None = None
    supplier_filing_period: str | None = None
    rate_items: list[dict] = field(default_factory=list)
    # The period of the statement this arrived in, which is not necessarily the
    # invoice's own period: a 2B carries late filings from earlier months. Only
    # the portal JSON declares it; a CSV export does not carry it.
    statement_period: str | None = None
    # On an amendment (b2ba, cdnra), the number of the document it amends.
    # The buyer booked the original; when the supplier's correction changes
    # the number, this is the only thing that ties the two together.
    original_invoice_number: str | None = None

    def __post_init__(self) -> None:
        # A credit note's direction is its document type, not its sign — see
        # :attr:`is_credit_note` — and every consumer subtracts its amounts.
        # The portal writes them positive, but this also reads CSV, and an ERP
        # or Tally export routinely writes a note as -9,000.00. Subtracting that
        # *added* ₹9,000 of credit: a note issued to take credit back raised the
        # eligible pool and the statement's summary by its own amount. The
        # magnitude is the amount; the type already says which way it goes.
        if self.is_credit_note:
            for name in ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value"):
                setattr(self, name, abs(getattr(self, name)))

    @property
    def total_tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess

    @property
    def is_credit_note(self) -> bool:
        """Whether this document *takes credit away* rather than granting it.

        The portal states the amounts on a credit note as positive figures and
        leaves the sign to ``document_type``, so a reader that goes by the money
        alone reads a reduction as a second supply. Only "C" reverses: a debit
        note ("D") raises the supplier's charge and the buyer's credit with it,
        which is the same direction as an invoice.
        """
        return self.document_type.strip().upper().startswith("C")

    def as_dict(self) -> dict:
        """JSON-safe form, for storing on the return row."""
        return {
            "supplier_gstin": self.supplier_gstin,
            "supplier_name": self.supplier_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "period": self.period,
            "place_of_supply": self.place_of_supply,
            "taxable_value": str(self.taxable_value),
            "cgst": str(self.cgst),
            "sgst": str(self.sgst),
            "igst": str(self.igst),
            "cess": str(self.cess),
            "total_value": str(self.total_value),
            "total_tax": str(self.total_tax),
            "itc_available": self.itc_available,
            "reverse_charge": self.reverse_charge,
            "document_type": self.document_type,
            "original_invoice_number": self.original_invoice_number,
            "supplier_filing_date": (
                self.supplier_filing_date.isoformat() if self.supplier_filing_date else None
            ),
            "supplier_filing_period": self.supplier_filing_period,
            "rate_items": self.rate_items,
            "statement_period": self.statement_period,
        }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _flag(value: object, *, default: bool = False) -> bool:
    """Read the portal's ``Y``/``N`` flags, and the words a CSV export uses.

    :func:`~app.services.invoice_parser.to_flag` is the one reader, shared with
    the extraction path, because both are being handed a human's answer to a
    yes/no question and there is nothing GSTR-2B-specific about what "no" looks
    like. It knows a few more spellings than this used to — "N/A", "Not
    applicable", "nil" — which a hand-edited export carries as readily as a
    photographed invoice does.
    """
    return to_flag(value, default=default)


def period_from_portal(value: object) -> str | None:
    """``"042026"`` (the portal's ``MMYYYY``) -> ``"2026-04"``.

    Also accepts a period already in ``YYYY-MM``, so a hand-built fixture and a
    real download go down the same path.
    """
    text = str(value or "").strip()
    # Validated rather than merely shaped: this is the one path by which a
    # period enters the database without passing a route's validation, and a
    # hand-edited statement claiming ``2026-13`` would be stored and then
    # reconciled against arithmetic that assumes the month exists.
    #
    # The assembled candidates go back through the same check rather than
    # trusting the month digits alone. ``129999`` is six digits with a real
    # month in front, and it used to be accepted and stored as ``9999-12`` — a
    # statement filed under a year whose due date ``date()`` will not construct,
    # so every screen scoped to that period answered 500 from then on. The
    # month was the only half of the field anyone was looking at.
    if gst_calendar.is_period(text):
        return text
    if re.fullmatch(r"\d{6}", text):
        for candidate in (
            f"{text[2:]}-{text[:2]}",  # MMYYYY, what the portal writes
            f"{text[:4]}-{text[4:]}",  # YYYYMM, what some exports write
        ):
            if gst_calendar.is_period(candidate):
                return candidate
    return None


def _period_of(record: GSTR2BRecord, fallback: str | None) -> str | None:
    """The filing period an invoice belongs to.

    The invoice date decides, not the statement it arrived in: a 2B for May
    routinely carries April invoices that the supplier filed late, and booking
    those against May would compare them with the wrong month's purchases.
    """
    if record.invoice_date:
        return record.invoice_date.strftime("%Y-%m")
    return fallback


# The longest an invoice number is under rule 46 of the CGST Rules, so a real
# one is always quoted whole; anything past it is a file that has been edited.
_MAX_QUOTED_NUMBER = 16


def _quoted(invoice_number: str | None) -> str:
    """An invoice number for an error message: whole if real, cut if not."""
    if not invoice_number:
        return "(unnumbered)"
    if len(invoice_number) <= _MAX_QUOTED_NUMBER:
        return invoice_number
    return invoice_number[:_MAX_QUOTED_NUMBER] + "…"


def _money(value: object) -> Decimal:
    # ``to_money`` rather than ``to_decimal``: a statement is a file someone
    # uploads, so nothing in it is trusted to be an amount a money column can
    # hold. ``json.loads`` accepts the bare ``Infinity`` token, and one of those
    # in a ``txval`` used to be summed into the stored statement, committed, and
    # only *then* refused by the response model — a 500 for the caller over a
    # row that is already there, and every later read of that period the same.
    return to_money(value) or ZERO


# ---------------------------------------------------------------------------
# Portal JSON
# ---------------------------------------------------------------------------

# Sections of ``docdata`` that describe an inward supply against a GSTIN.
# Credit and debit notes live in ``cdnr`` and carry ``nt`` rather than ``inv``.
_INVOICE_SECTIONS = ("b2b", "b2ba")
_NOTE_SECTIONS = ("cdnr", "cdnra")


def _unwrap_docdata(payload: dict) -> dict:
    """Find the ``docdata`` block, wherever this particular export buried it.

    Callers validate that *payload* is an object before getting here.
    """
    for candidate in (
        payload.get("data", {}).get("docdata") if isinstance(payload.get("data"), dict) else None,
        payload.get("docdata"),
        payload.get("data") if isinstance(payload.get("data"), dict) else None,
        payload,
    ):
        if isinstance(candidate, dict) and any(
            key in candidate for key in _INVOICE_SECTIONS + _NOTE_SECTIONS
        ):
            return candidate
    raise GSTR2BParseError(
        "No b2b or cdnr section found. Expected a GSTR-2B download from the GST portal."
    )


def _statement_period(payload: dict) -> str | None:
    for holder in (payload.get("data") if isinstance(payload.get("data"), dict) else None, payload):
        if isinstance(holder, dict):
            found = period_from_portal(holder.get("rtnprd"))
            if found:
                return found
    return None


def _addressed_to(payload: dict) -> str | None:
    """The buyer GSTIN the portal stamped on the statement, if it carries one.

    A GSTR-2B is not a generic document: the portal generates one per
    registration, and ``gstin`` at the top of the envelope says whose inward
    supplies these are. Sitting beside ``rtnprd`` and read the same way, since
    exports differ on whether the envelope is wrapped in ``data``.

    ``None`` when the field is absent or unreadable, which is the ordinary case
    for a CSV export — those have no envelope at all, only the table. The
    caller decides what an unknown addressee means; it is not this module's
    place to refuse a file the portal plainly produced.
    """
    for holder in (payload.get("data") if isinstance(payload.get("data"), dict) else None, payload):
        if isinstance(holder, dict):
            found = gstin_service.normalize(str(holder.get("gstin") or ""))
            if found:
                return found
    return None


def recipient_gstin(content: bytes, filename: str | None = None) -> str | None:
    """Whose GSTR-2B this file is, or ``None`` when the file does not say.

    Separate from :func:`parse` rather than carried on every record: this is a
    fact about the statement, not about any invoice in it, and putting it on
    fifteen hundred records would invite a reader to think it could differ
    between them.

    A 2B is addressed to one registration, and importing one addressed to
    another is the mistake a practice with several clients on one login is
    exactly placed to make — three browser tabs, three downloads, one of them
    dropped into the wrong tenant. Nothing downstream notices: every purchase
    in the books reconciles as missing from the statement, every document in
    the statement as missing from the books, and the screen reports the whole
    period's credit at risk. That reads as a catastrophic supplier failure and
    is a mis-click, and there is nothing on the screen to tell the two apart.
    """
    if not content:
        return None
    text = content.decode("utf-8-sig", errors="replace").lstrip()
    if not (text.startswith(("{", "[")) or (filename or "").lower().endswith(".json")):
        return None
    try:
        payload = json.loads(text)
        # Inside the guard, for the reason :func:`parse_json` gives: from
        # Python 3.13 a deeply nested document parses, and ``str()`` of a
        # ``gstin`` holding one is then the first thing to recurse.
        return _addressed_to(payload) if isinstance(payload, dict) else None
    except (ValueError, RecursionError):
        # Not readable as JSON, so :func:`parse` is about to say so properly.
        return None


def _as_list(value: object) -> list:
    """*value* when it is a list, and an empty list otherwise.

    Used at the two places a GSTR-2B nests one list inside another. A dict or a
    string is iterable but yields keys and characters, never documents, so it
    is treated the same as a number: nothing to read here.
    """
    return value if isinstance(value, list) else []


def _flatten_item(item: dict) -> dict:
    """One rate line, with a nested ``itm_det`` folded up into it.

    ``itm_det`` is only honoured when it is itself an object. A file that
    carries a number or a list there is malformed, and unpacking it raised a
    ``TypeError`` out of the middle of the parse — which reaches the caller as
    a 500 rather than as the "this is not a readable 2B" the endpoint exists to
    say. The rest of the line is still readable, so the bad nesting is dropped
    rather than the invoice.
    """
    nested = item.get("itm_det")
    base = nested if isinstance(nested, dict) else {}
    return {**base, **{k: v for k, v in item.items() if k != "itm_det"}}


def _items_of(document: dict) -> list[dict]:
    """The rate-wise lines of an invoice or note, whichever key holds them."""
    for key in ("items", "itms"):
        value = document.get(key)
        if isinstance(value, list):
            # b2b items are flat dicts; some exports nest them under "itm_det".
            return [_flatten_item(item) if isinstance(item, dict) else {} for item in value]
    return []


def _record_from_document(
    document: dict, supplier: dict, *, is_note: bool, fallback_period: str | None
) -> GSTR2BRecord:
    items = _items_of(document)
    record = GSTR2BRecord(
        supplier_gstin=gstin_service.normalize(str(supplier.get("ctin") or "")) or None,
        supplier_name=(supplier.get("trdnm") or supplier.get("lgnm") or None),
        # ``inum`` on an invoice, ``nt_num`` on a credit/debit note.
        invoice_number=str(
            document.get("inum") or document.get("nt_num") or document.get("ntnum") or ""
        ).strip()
        or None,
        # ``dt`` on an invoice; a note dates itself, and the exports disagree
        # about the underscore exactly as they do on the number beside it.
        # Reading only ``nt_dt`` left a note carrying ``ntdt`` with no date at
        # all, so :func:`_period_of` fell back to the statement it arrived in —
        # and a note is in the statement for the month the supplier filed it,
        # which for a late filing is not the month it was issued. The document
        # then reversed credit in the wrong period.
        invoice_date=to_date(
            document.get("dt") or document.get("nt_dt") or document.get("ntdt")
        ),
        place_of_supply=str(document.get("pos") or "").strip()[:2] or None,
        total_value=_money(document.get("val")),
        itc_available=_flag(document.get("itcavl"), default=True),
        reverse_charge=_flag(document.get("rev"), default=False),
        # ``ntty`` is what the note sections carry in the exports built off the
        # GSTR-1 schema; ``typ`` is what the 2B download writes. Read only
        # ``typ``, a note declaring itself in ``ntty`` arrived with no type and
        # fell to the "C" default below — so a *debit* note, which raises the
        # supplier's charge and the buyer's credit with it, was read as a credit
        # note and taken off the pool instead of added to it. The tax moves
        # twice, in the wrong direction, on a document the portal was explicit
        # about.
        document_type=str(
            document.get("typ")
            or document.get("ntty")
            or document.get("nt_typ")
            or ("C" if is_note else "R")
        ).strip().upper() or "R",
        supplier_filing_date=to_date(supplier.get("supfildt")),
        supplier_filing_period=period_from_portal(supplier.get("supprd")),
        statement_period=fallback_period,
        # ``oinum`` on an amended invoice, ``ontnum``/``ont_num`` on an amended
        # note; absent everywhere else.
        original_invoice_number=str(
            document.get("oinum") or document.get("ontnum") or document.get("ont_num") or ""
        ).strip()
        or None,
    )

    for item in items:
        record.taxable_value += _money(item.get("txval"))
        record.cgst += _money(item.get("cgst"))
        record.sgst += _money(item.get("sgst"))
        record.igst += _money(item.get("igst"))
        record.cess += _money(item.get("cess"))
        record.rate_items.append(
            {
                "rate": str(to_decimal(item.get("rt"), default=None) or ""),
                "taxable_value": str(_money(item.get("txval"))),
                "cgst": str(_money(item.get("cgst"))),
                "sgst": str(_money(item.get("sgst"))),
                "igst": str(_money(item.get("igst"))),
                "cess": str(_money(item.get("cess"))),
            }
        )

    if not record.total_value:
        record.total_value = record.taxable_value + record.total_tax
    record.period = _period_of(record, fallback_period)
    return record


def parse_json(payload: dict | str | bytes) -> list[GSTR2BRecord]:
    """Every inward document in a portal GSTR-2B, as flat records."""
    try:
        if isinstance(payload, bytes | str):
            payload = json.loads(payload)
        # An escaped half-pair in an invoice number or trade name was stored as
        # written, and every later response that serialised the row was a 500.
        payload = encodable(payload)
    # A few kilobytes of ``[[[[…`` is a RecursionError rather than a
    # ValueError — and was a 500 on an upload whose only fault is that it is
    # not a GSTR-2B. Which call raises it depends on the interpreter: up to
    # 3.12 ``json.loads`` recurses once per nesting level and gives up itself,
    # while from 3.13 it parses any depth and the first thing to recurse is
    # the ``encodable`` walk. Guarding only the parse was correct on the 3.12
    # this ships on and a 500 on anything newer, so both sit under one guard
    # and the answer does not depend on which Python is running.
    except (ValueError, RecursionError) as exc:
        raise GSTR2BParseError(
            "This file is not valid JSON, or is nested far deeper than a "
            "GSTR-2B. Upload the unmodified download from the GST portal."
        ) from exc
    if not isinstance(payload, dict):
        raise GSTR2BParseError(
            "This file is not a GSTR-2B download. Upload the unmodified "
            "file from the GST portal."
        )

    docdata = _unwrap_docdata(payload)
    fallback_period = _statement_period(payload)
    records: list[GSTR2BRecord] = []

    for section in _INVOICE_SECTIONS + _NOTE_SECTIONS:
        is_note = section in _NOTE_SECTIONS
        # A section, and a supplier's document list inside it, are lists in
        # every 2B the portal produces. Iterating whatever else turned up threw
        # ``TypeError: 'int' object is not iterable`` from inside the parse, and
        # an upload the caller could plainly see was malformed came back as a
        # 500 with a correlation id instead of the 400 that names the problem.
        # Anything that is not a list of objects carries no invoice to read, so
        # it is skipped and the rest of the file is still imported.
        for supplier in _as_list(docdata.get(section)):
            if not isinstance(supplier, dict):
                continue
            documents = _as_list(supplier.get("inv") or supplier.get("nt"))
            for document in documents:
                if not isinstance(document, dict):
                    continue
                records.append(
                    _record_from_document(
                        document, supplier, is_note=is_note, fallback_period=fallback_period
                    )
                )
    return records


# ---------------------------------------------------------------------------
# CSV / Excel export
# ---------------------------------------------------------------------------

# Portal column headings -> record field. Matched on a squashed form of the
# heading (lower-cased, non-alphanumerics removed) so that the spacing,
# punctuation and casing drift between portal versions stops mattering.
_CSV_COLUMNS: dict[str, str] = {
    "gstinofsupplier": "supplier_gstin",
    "suppliergstin": "supplier_gstin",
    "gstin": "supplier_gstin",
    "ctin": "supplier_gstin",
    "tradelegalname": "supplier_name",
    "tradename": "supplier_name",
    "legalname": "supplier_name",
    "suppliername": "supplier_name",
    "invoicenumber": "invoice_number",
    "invoiceno": "invoice_number",
    "invoicedetailsinvoicenumber": "invoice_number",
    "documentnumber": "invoice_number",
    "notenumber": "invoice_number",
    "invoicedate": "invoice_date",
    "documentdate": "invoice_date",
    "notedate": "invoice_date",
    "invoicevalue": "total_value",
    "invoicevaluers": "total_value",
    "documentvalue": "total_value",
    "notevalue": "total_value",
    "placeofsupply": "place_of_supply",
    "supplyattractreversecharge": "reverse_charge",
    "reversecharge": "reverse_charge",
    "rate": "tax_rate",
    "ratepercent": "tax_rate",
    "taxablevalue": "taxable_value",
    "taxablevaluers": "taxable_value",
    "integratedtax": "igst",
    "integratedtaxrs": "igst",
    "igst": "igst",
    "centraltax": "cgst",
    "centraltaxrs": "cgst",
    "cgst": "cgst",
    "stateuttax": "sgst",
    "stateuttaxrs": "sgst",
    "sgst": "sgst",
    "cess": "cess",
    "cessrs": "cess",
    "itcavailability": "itc_available",
    "availabilityofitc": "itc_available",
    "gstr1filingdate": "supplier_filing_date",
    "gstr13bfilingdate": "supplier_filing_date",
    "gstr1gstr5filingdate": "supplier_filing_date",
    # The heading the portal actually ships, once IFF was folded in.
    "gstr1iffgstr5filingdate": "supplier_filing_date",
    "gstr1gstr5period": "supplier_filing_period",
    "gstr1iffgstr5period": "supplier_filing_period",
    "gstr1period": "supplier_filing_period",
    # The B2BA and CDNRA sheets of the portal's export: the document the row
    # amends. Read from JSON as ``oinum``; without these the CSV route lost it,
    # and a renumbered correction was reported twice (see ``match``).
    "originalinvoicenumber": "original_invoice_number",
    "originalinvoiceno": "original_invoice_number",
    "originaldocumentnumber": "original_invoice_number",
    "originalnotenumber": "original_invoice_number",
    "invoicetype": "document_type",
    "documenttype": "document_type",
    "notetype": "document_type",
}


def _squash(heading: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (heading or "").lower())


def _document_class(declared_type: str) -> str:
    """Which of the three registers a document type belongs to.

    One letter decides it, because the column carries whatever the export
    wrote — "C", "Credit note", "CRED" — and the class has to be the same for
    every rate line of one document however the wording drifts down the file.

    "Deemed exports" also begins with a D and so lands with the debit notes.
    That is harmless: the class is a grouping key, never a direction — only
    :attr:`GSTR2BRecord.is_credit_note` decides which way money moves — and it
    would take a supplier numbering a deemed-export invoice and a debit note
    alike for the two to meet at all.
    """
    if declared_type.startswith("C"):
        return "C"
    if declared_type.startswith("D"):
        return "D"
    return "R"


def _find_header_row(rows: list[list[str]]) -> int:
    """Index of the header row.

    The portal's CSV opens with title and legend rows before the real headings,
    so the header is found by looking for the row that names a supplier GSTIN
    column rather than by assuming row 0.
    """
    for index, row in enumerate(rows[:30]):
        squashed = {_squash(cell) for cell in row}
        if squashed & {"gstinofsupplier", "suppliergstin", "ctin", "gstin"}:
            return index
    return 0


def parse_csv(content: str | bytes) -> list[GSTR2BRecord]:
    """Read a CSV export, summing its rate-wise rows back into invoices."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    try:
        rows = [
            row for row in csv.reader(io.StringIO(content)) if any(cell.strip() for cell in row)
        ]
    except csv.Error as exc:
        # A cell past the module's field limit (128 KiB), or a NUL the reader
        # refuses: either way not a portal export, and a 500 was the answer.
        raise GSTR2BParseError(
            "This file could not be read as CSV. Upload the JSON download from "
            "the GST portal, or a CSV export of it."
        ) from exc
    if not rows:
        raise GSTR2BParseError(
            "The file has no data rows. It may still be downloading, or "
            "it may be an empty export from the GST portal."
        )

    header_index = _find_header_row(rows)
    headings = [_squash(cell) for cell in rows[header_index]]
    if not any(headings):
        raise GSTR2BParseError(
            "No column headings found in the file. Expected a GSTR-2B "
            "CSV export from the GST portal."
        )

    mapped = {index: _CSV_COLUMNS[key] for index, key in enumerate(headings) if key in _CSV_COLUMNS}
    if "supplier_gstin" not in mapped.values():
        raise GSTR2BParseError(
            "No supplier GSTIN column found. Expected a GSTR-2B export with a "
            "'GSTIN of supplier' column."
        )

    # Rate-wise rows of one document are merged, keyed the way the portal
    # identifies one: supplier, document number — and whether the document
    # *grants* credit or takes it away.
    #
    # That third part was missing, and the two series it separates collide
    # constantly: an invoice register and a credit-note register both restart at
    # 1 each year, so one supplier's invoice 001 and credit note 001 are the
    # ordinary case rather than a contrived one. Merged into a single record,
    # the note's figures were *added* to the invoice's — and the merged row kept
    # the type of whichever came first, so with the invoice in front it was no
    # longer a credit note at all. Reconciliation then counted the reversal as
    # extra supply: the eligible pool came out over by twice the note's tax,
    # once for the credit that should have gone and once for the credit that
    # should never have arrived. This CSV reader has always been expected to
    # carry notes — ``notenumber``, ``notedate`` and ``notetype`` are in the
    # column map above.
    merged: dict[tuple[str, str, str], GSTR2BRecord] = {}
    order: list[tuple[str, str, str]] = []
    # The key each document number is currently open under, so a continuation
    # rate line whose type cell is blank joins the document it belongs to rather
    # than starting a second one. Exports vary on whether the type is repeated
    # down the rate lines of one document, and a file with no type column at all
    # — which is most of them — must go on merging exactly as it did before.
    open_under: dict[tuple[str, str], tuple[str, str, str]] = {}

    for row in rows[header_index + 1 :]:
        values: dict[str, str] = {}
        for index, field_name in mapped.items():
            if index < len(row):
                values.setdefault(field_name, row[index].strip())

        supplier_gstin = gstin_service.normalize(values.get("supplier_gstin", "")) or None
        invoice_number = (values.get("invoice_number") or "").strip() or None
        # A total row, or trailing notes under the table. The blank-cell test
        # this used to be missed the commoner shape of one: a footer that puts
        # its *label* in the first column, which is the supplier GSTIN column.
        # "Total" normalised to "TOTAL", passed as a supplier, and the row's
        # figures — which are the section's own figures again — were added to
        # the statement a second time. A two-invoice export came out with three
        # documents and twice the credit, and reconciliation reported the extra
        # one as a portal document missing from the books.
        #
        # So a row earns its place by carrying a document number, or by naming
        # a supplier that is actually a GSTIN. A real 2B row always does one:
        # every supplier in a statement is a live registration, and the check
        # digit is what a footer label cannot fake.
        if not invoice_number and not gstin_service.is_valid(supplier_gstin or ""):
            continue

        # Only the class of document goes in the key, not the spelling: "C",
        # "Credit note" and "CRED" are one class, and splitting on the wording
        # would put two rate lines of one note in two records. Debit notes are
        # their own class rather than being folded in with invoices — both add
        # to the statement, so the totals would survive the merge, but the
        # merged row carries one document's date and value and reconciliation
        # then reports the book invoice as disagreeing with a portal row that is
        # two documents added together.
        declared_type = (values.get("document_type") or "").strip().upper()[:4]
        number_key = (supplier_gstin or "", invoice_number or "")
        if declared_type:
            key = (*number_key, _document_class(declared_type))
        else:
            key = open_under.get(number_key) or (*number_key, "R")
        open_under[number_key] = key

        record = merged.get(key)
        if record is None:
            record = GSTR2BRecord(
                supplier_gstin=supplier_gstin,
                supplier_name=values.get("supplier_name") or None,
                invoice_number=invoice_number,
                invoice_date=to_date(values.get("invoice_date")),
                place_of_supply=(values.get("place_of_supply") or "").strip()[:2] or None,
                total_value=_money(values.get("total_value")),
                reverse_charge=_flag(values.get("reverse_charge")),
                document_type=declared_type or "R",
                supplier_filing_date=to_date(values.get("supplier_filing_date")),
                supplier_filing_period=period_from_portal(values.get("supplier_filing_period")),
                original_invoice_number=(values.get("original_invoice_number") or "").strip()
                or None,
            )
            merged[key] = record
            order.append(key)

        record.taxable_value += _money(values.get("taxable_value"))
        record.cgst += _money(values.get("cgst"))
        record.sgst += _money(values.get("sgst"))
        record.igst += _money(values.get("igst"))
        record.cess += _money(values.get("cess"))

        # One ineligible line makes the invoice's credit partial; treating it
        # as available would overstate the claim. Latched, so a later rate line
        # that says nothing cannot hand the credit back.
        #
        # Read with :func:`_flag` rather than against a set of its own. The
        # private set this used to check knew four spellings of "no" and the
        # shared reader knew eleven, and neither was a superset of the other, so
        # the same answer was read differently depending on which shape a
        # business happened to upload: a CSV saying "N/A", "Nil", "None",
        # "False", "0" or "-" was read as credit *available*, and so was a JSON
        # saying "Not available" — the words this column is actually about.
        # Both gaps run one way. Credit the portal has withheld is counted as
        # claimable, so the tax lands in ``itc_eligible`` instead of
        # ``itc_at_risk`` and nothing tells the business the claim is the one
        # the notice will be about.
        #
        # ``default=True`` because a blank cell is not a refusal — most exports
        # leave the column empty on the rate lines below the first — and because
        # it is the default the portal's own ``itcavl`` carries.
        if not _flag(values.get("itc_available"), default=True):
            record.itc_available = False

        record.rate_items.append(
            {
                "rate": (values.get("tax_rate") or "").strip(),
                "taxable_value": str(_money(values.get("taxable_value"))),
                "cgst": str(_money(values.get("cgst"))),
                "sgst": str(_money(values.get("sgst"))),
                "igst": str(_money(values.get("igst"))),
                "cess": str(_money(values.get("cess"))),
            }
        )

    records = [merged[key] for key in order]
    for record in records:
        if not record.total_value:
            record.total_value = record.taxable_value + record.total_tax
        record.period = _period_of(record, None)
    return records


# The figures every reader accumulates, and every one of them ends up in a
# ``Numeric(16, 2)`` — on the record it is summed onto, and again in the
# statement totals :func:`~app.services.reconciliation.summarise_records`
# writes to ``gstr_returns``.
_MONEY_FIELDS = ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value")


def _refuse_money_no_column_could_hold(records: list[GSTR2BRecord]) -> None:
    """Refuse a statement whose figures will not fit the columns that store them.

    :func:`_money` bounds each cell it reads and stops there, which leaves the
    *addition* unbounded — and every figure in a 2B is an addition. A rate line
    is summed onto its invoice, and every invoice is summed into the period
    totals, so a hundred cells each just inside ``MONEY_MAX`` store a figure a
    hundred times wider than the column holds. Five rate items at the ceiling
    on one invoice was enough to reach it.

    The failure is the split this product keeps meeting from the other side:
    Postgres refuses the INSERT with ``numeric field overflow`` and SQLite
    keeps whatever it was handed, so the deployment answers 500 on an import
    that the suite watches succeed. The import is also the wrong end to notice
    it at — the row is written and committed before any response model looks at
    the number.

    So it is checked here, before anything is stored, and the whole file is
    refused rather than the offending line dropped. A statement is a single
    document that has to add up: silently discarding one rate line would leave
    a stored 2B whose totals disagree with the portal's, which is worse than
    saying the file cannot be read — and no real statement is anywhere near
    ninety-nine thousand crore, so anything that gets here is corrupt or
    hand-edited rather than large.

    Magnitudes are summed, not signed amounts, so a credit note cannot net a
    pair of impossible figures back into range on the way past.
    """
    for record in records:
        for name in _MONEY_FIELDS:
            if abs(getattr(record, name)) > MONEY_MAX:
                # Quoted so the reader can find the line, and cut so the
                # sentence survives the quoting: the number is whatever the
                # file said it was, and a corrupt file — which is what a
                # figure this size means — is not one whose fields are the
                # length a GST invoice number is.
                raise GSTR2BParseError(
                    f"Invoice {_quoted(record.invoice_number)} totals "
                    f"{getattr(record, name)} in {name.replace('_', ' ')}, which is "
                    "larger than any invoice carries. Check the file — its rate "
                    "lines do not add up to a real document."
                )

    for name in _MONEY_FIELDS:
        total = sum((abs(getattr(record, name)) for record in records), ZERO)
        if total > MONEY_MAX:
            raise GSTR2BParseError(
                f"The {name.replace('_', ' ')} in this file totals {total}, which is "
                "larger than any GSTR-2B carries. Check that this is an unedited "
                "download from the GST portal."
            )


def parse(content: bytes, filename: str | None = None) -> list[GSTR2BRecord]:
    """Parse a GSTR-2B upload, choosing the reader by content rather than name.

    The extension is only a tiebreaker: businesses rename these files freely,
    and a ``.txt`` holding portal JSON is common enough to be worth handling.

    Both readers hand their records through
    :func:`_refuse_money_no_column_could_hold` on the way out, because the
    ceiling that matters is on the sums they build rather than on the cells
    they read, and this is the door every caller comes through.
    """
    if not content:
        raise GSTR2BParseError(
            "The uploaded file is empty. It may still be downloading — "
            "try again once the download finishes."
        )

    text = content.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    lowered = (filename or "").lower()

    if stripped.startswith(("{", "[")) or lowered.endswith(".json"):
        records = parse_json(text)
    elif lowered.endswith((".xlsx", ".xls", ".xlsm")):
        raise GSTR2BParseError(
            "Excel GSTR-2B files are not supported yet. Save the sheet as CSV, "
            "or upload the JSON download from the GST portal."
        )
    else:
        records = parse_csv(text)

    _refuse_money_no_column_could_hold(records)
    return records
