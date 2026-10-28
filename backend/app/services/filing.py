"""Turning the books into something the GST portal will accept.

Three jobs, in the order a business does them:

1. **Validate.** Catch what the portal will reject, plus what it will silently
   accept and the department will query later. A rejected upload costs an
   afternoon; an accepted-but-wrong return costs interest and a notice, so both
   classes of problem are reported and the second is not treated as cosmetic.
2. **Generate.** Build GSTR-1 from sales invoices and pre-fill GSTR-3B from the
   matched position, in the portal's own JSON shape.
3. **Export.** JSON for the offline utility, CSV for a human to read or a CA to
   check before anything is filed.

The portal's schema is the contract and it changes on the government's
timetable, so the shapes here are built explicitly rather than derived from the
ORM: when the schema moves, the diff should land in this file and nowhere else.

Two conventions the portal uses and nothing else does:

* ``fp`` / ``ret_period`` is ``MMYYYY``. Not ``YYYY-MM``, which is what the
  rest of this codebase stores.
* Invoice dates are ``dd-mm-yyyy``.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.sanitize import csv_safe
from app.models.business import Business
from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import (
    UNCOUNTABLE_STATUSES,
    Invoice,
    InvoiceStatus,
    InvoiceType,
    without_document,
)
from app.services import gst_calendar, invoice_parser, invoice_service
from app.services import gstin as gstin_service
from app.services import itc as itc_service

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")

# The rates GST actually levies. A rate outside this set is a data-entry error
# every time — there is no 15% or 20% slab — and the portal rejects it.
#
# Imported rather than restated. This file and the parser each held a list, and
# they had drifted apart: the parser's was short five slabs, so it dropped the
# rate off any invoice on one of them, and the check below then had no rate to
# verify the tax against. Two lists of what GST charges is one of them being
# wrong, and neither module is the obvious loser when they disagree.
VALID_RATES = invoice_parser.VALID_TAX_RATES

# Tolerance when checking that tax equals rate x taxable value, or that the
# total equals value plus tax. Both sides round independently at the line and
# at the invoice, and a rupee of arithmetic is not a filing error.
ARITHMETIC_TOLERANCE = Decimal("1.00")

# Above this invoice value an inter-state B2C supply must be reported
# invoice-by-invoice (B2CL) rather than in the rate-wise B2CS summary.
#
# The limit moved. Notification 12/2024-Central Tax replaced "two and a half
# lakh rupees" with "one lakh rupees" in table 5 of FORM GSTR-1, and the portal
# has applied the lower figure since the November 2024 return. Every period this
# product will ever file is past that, so the old limit is kept only so that
# re-generating a return for a period that was filed under it reproduces what
# was filed — which is the same reason ``build_gstr3b`` anchors Rule 37 to the
# close of the period rather than to today.
#
# The direction of the error matters. Filing a ₹1.5 lakh inter-state B2C supply
# in the rate-wise summary does not lose the money — the tax is declared either
# way — it drops the invoice-level detail the table exists to carry, and a
# return missing detail the schema requires is one the department can ask about
# long after the cash has been paid.
B2CL_THRESHOLD = Decimal("100000.00")
B2CL_THRESHOLD_BEFORE_NOV_2024 = Decimal("250000.00")
B2CL_THRESHOLD_LOWERED_FROM = "2024-11"


def b2cl_threshold(period: str) -> Decimal:
    """The B2CL limit that applied to *period*."""
    return (
        B2CL_THRESHOLD
        if period >= B2CL_THRESHOLD_LOWERED_FROM
        else B2CL_THRESHOLD_BEFORE_NOV_2024
    )

# The portal's schema version at the time of writing. Sent verbatim in the
# envelope; the offline utility checks it.
GSTR1_VERSION = "GST3.0.4"


class Severity(str, Enum):
    """Whether a finding stops a filing or merely ought to be looked at."""

    ERROR = "error"  # The portal will reject this, or the figure is wrong.
    WARNING = "warning"  # Filing will succeed; the department may still ask.


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_portal_period(period: str) -> str:
    """``2026-04`` -> ``042026``, the portal's ``fp``/``ret_period`` form."""
    year, month = period.split("-")
    return f"{month}{year}"


def to_portal_date(value: date | None) -> str | None:
    """``date(2026, 4, 15)`` -> ``15-04-2026``."""
    return value.strftime("%d-%m-%Y") if value else None


def _tax_total(invoice: Invoice) -> Decimal:
    return (
        (invoice.igst or ZERO)
        + (invoice.cgst or ZERO)
        + (invoice.sgst or ZERO)
        + (invoice.cess or ZERO)
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """One problem found on one invoice, before anything is filed."""

    invoice_id: int | None
    invoice_number: str | None
    field: str
    severity: Severity
    message: str

    def as_dict(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "field": self.field,
            "severity": self.severity.value,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    """Everything wrong with a period, and whether it can be filed."""

    period: str
    issues: list[ValidationIssue] = field(default_factory=list)
    invoice_count: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """True when nothing blocks a filing. Warnings do not block."""
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "ok": self.ok,
            "invoice_count": self.invoice_count,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.as_dict() for issue in self.issues],
        }


# Rule 46(b) of the CGST Rules: a serial number "not exceeding sixteen
# characters ... containing alphabets or numerals or special characters hyphen
# or dash and slash". A space, a hash or a rupee sign is not one of them, and
# the portal rejects the return rather than the line.
RULE_46_INVOICE_NUMBER = re.compile(r"[A-Za-z0-9/-]+")
# The same set, one character at a time, so a message can name what it found
# rather than telling someone their number is wrong and leaving them to spot
# which of sixteen characters did it.
_RULE_46_CHAR = re.compile(r"[A-Za-z0-9/-]")


def validate_invoice(
    invoice: Invoice, *, business_state: str | None, period: str
) -> list[ValidationIssue]:
    """Everything wrong with one invoice, from the portal's point of view."""
    issues: list[ValidationIssue] = []

    def add(field_name: str, severity: Severity, message: str) -> None:
        issues.append(
            ValidationIssue(
                invoice_id=invoice.id,
                invoice_number=invoice.invoice_number,
                field=field_name,
                severity=severity,
                message=message,
            )
        )

    is_sales = invoice.invoice_type == InvoiceType.SALES

    # ---- Identity ----
    if not invoice.invoice_number:
        add("invoice_number", Severity.ERROR, "Invoice number is missing")
    else:
        if len(invoice.invoice_number) > 16:
            # The portal caps invoice numbers at 16 characters.
            add(
                "invoice_number",
                Severity.ERROR,
                f"Invoice number is {len(invoice.invoice_number)} characters; the portal allows 16",
            )
        # Rule 46(b) allows letters, digits, hyphen and slash, and nothing
        # else. So "INV#42" and "INV 42" are numbers the portal refuses the
        # whole return over — one line rejects the upload, not the invoice.
        #
        # Reported alongside the length rather than instead of it: they are
        # two independent things wrong with the same string, and an "elif"
        # sends someone back to the portal a second time to be told about the
        # half they were not shown.
        #
        # Sales only. On a purchase this string is the supplier's serial, copied
        # off their document — it is what GSTR-2B will carry too, so it matches
        # exactly as well as a compliant one, and complaining about it would be
        # asking a business to correct a number it has no authority to change.
        if is_sales and not RULE_46_INVOICE_NUMBER.fullmatch(invoice.invoice_number):
            offending = sorted(
                {c for c in invoice.invoice_number if not _RULE_46_CHAR.fullmatch(c)}
            )
            add(
                "invoice_number",
                Severity.ERROR,
                f"Invoice number '{invoice.invoice_number}' contains "
                + ", ".join(f"'{c}'" for c in offending)
                + ". Rule 46(b) allows letters, digits, '-' and '/' only.",
            )

    if invoice.invoice_date is None:
        add("invoice_date", Severity.ERROR, "Invoice date is missing")
    elif invoice.period and invoice.period != period:
        add(
            "invoice_date",
            Severity.WARNING,
            f"Dated {invoice.period}, being filed under {period}",
        )

    # ---- Counterparty ----
    if invoice.counterparty_gstin:
        if not gstin_service.is_valid(invoice.counterparty_gstin):
            add(
                "counterparty_gstin",
                Severity.ERROR,
                f"{invoice.counterparty_gstin} is not a valid GSTIN",
            )
    elif is_sales:
        # A sale without a counterparty GSTIN is B2C, which is legitimate — it
        # just files in a different block, so this is worth saying rather than
        # failing on.
        add(
            "counterparty_gstin",
            Severity.WARNING,
            "No GSTIN — will be filed as a B2C supply",
        )
    else:
        # A purchase without a supplier GSTIN can never be matched in GSTR-2B,
        # so the credit on it is unclaimable until someone fills it in.
        add(
            "counterparty_gstin",
            Severity.ERROR,
            "Supplier GSTIN is missing; ITC cannot be claimed without it",
        )

    # ---- HSN ----
    if not invoice.hsn_code:
        add("hsn_code", Severity.WARNING, "HSN code is missing")
    elif not invoice.hsn_code.isdigit() or len(invoice.hsn_code) not in (4, 6, 8):
        add(
            "hsn_code",
            Severity.ERROR,
            f"HSN '{invoice.hsn_code}' must be 4, 6 or 8 digits",
        )

    # ---- Money ----
    tax = _tax_total(invoice)
    taxable = invoice.taxable_value or ZERO

    if taxable <= ZERO and tax <= ZERO:
        add("taxable_value", Severity.ERROR, "Invoice has no taxable value and no tax")
    elif taxable <= ZERO:
        # Tax on nothing. GST is a percentage of a value, so there is no rate
        # and no supply that produces this — it is an extraction that read the
        # tax boxes off the document and missed the one they were computed
        # from, which is a common enough way for a photographed invoice to come
        # back.
        #
        # Caught here or not at all. The rate cross-check below is skipped when
        # there is no taxable value to apply a rate to, and the check above only
        # fires when *both* are empty, so an invoice carrying ₹18,000 of IGST
        # against a taxable value of zero validated completely clean. It then
        # filed as a rate-zero line carrying tax — ``_rate_of`` derives the rate
        # from the figures and gets 0% — which the portal rejects on upload.
        # That is the afternoon this module exists to save.
        add(
            "taxable_value",
            Severity.ERROR,
            f"Tax of {_q(tax)} on a taxable value of zero. Tax is a percentage "
            "of a value, so the value is missing rather than nil.",
        )

    if invoice.tax_rate is not None and invoice.tax_rate not in VALID_RATES:
        add(
            "tax_rate",
            Severity.ERROR,
            f"{invoice.tax_rate}% is not a GST rate",
        )

    # Tax should be the rate applied to the taxable value — checked against the
    # rates this invoice will actually be *filed* at, which is not always the
    # rate stored on it.
    #
    # It used to be checked only when ``tax_rate`` was set, on the grounds that
    # a multi-rate invoice has no one rate to apply. But the return still has to
    # declare a rate for every rupee, so :func:`rate_lines` finds one either way:
    # from the stored breakdown where there is a usable one, and otherwise by
    # deriving a single rate from the totals and snapping it to the nearest real
    # slab. An invoice carrying ₹1,150 of tax on ₹10,000 is filed at 12% — the
    # closest slab to the 11.5% the figures imply — and 12% of ₹10,000 is
    # ₹1,200. The portal rejects that line, and validation, which exists to say
    # so before an afternoon is spent, was silent on precisely the invoices
    # whose rate it could not read.
    if taxable > ZERO:
        lines = rate_lines(invoice)
        expected = _q(
            sum((line.rate * line.taxable_value for line in lines), ZERO) / Decimal("100")
        )
        charged = tax - (invoice.cess or ZERO)  # Cess is levied on its own base.
        if abs(charged - expected) > ARITHMETIC_TOLERANCE:
            if invoice.tax_rate is not None:
                message = (
                    f"Tax of {charged} does not match {invoice.tax_rate}% of {taxable} "
                    f"({expected})"
                )
            elif len(lines) > 1:
                rates = ", ".join(f"{line.rate}%" for line in lines)
                message = (
                    f"Tax of {charged} does not match the rate-wise breakdown this will "
                    f"be filed at ({rates}), which comes to {expected}"
                )
            else:
                message = (
                    f"Tax of {charged} matches no GST rate on {taxable}. It will be filed "
                    f"at {lines[0].rate}%, the nearest slab, which is {expected}. Set the "
                    "rate or correct the tax."
                )
            add("tax_rate", Severity.ERROR, message)

    if invoice.total_value and abs(invoice.total_value - (taxable + tax)) > (
        ARITHMETIC_TOLERANCE
    ):
        add(
            "total_value",
            Severity.ERROR,
            f"Total {invoice.total_value} does not equal taxable {taxable} plus tax {tax}",
        )

    # ---- The IGST / CGST+SGST split ----
    # Which applies is decided by where the supply goes, not by preference, and
    # getting it wrong means tax paid to the wrong government — recoverable
    # only by amending the return.
    #
    # s.7 and s.8 of the IGST Act put it as: the supply is inter-state when the
    # *supplier's* location and the place of supply are in different states. So
    # which end of the invoice is the supplier decides what to compare against,
    # and it is not the same end in both directions. On a sale we are the
    # supplier; on a purchase the counterparty is, and the place of supply is
    # our own state — which is exactly what a vendor prints on the invoice, and
    # what the parser reads off it.
    #
    # Comparing the place of supply with our own state either way made the
    # answer depend on whether the parser found the field. An inter-state
    # purchase with the place of supply read off it came out as "intra-state
    # supply in 27 carrying IGST" — a blocking error on a correct invoice —
    # while the same purchase with the field missing passed. The genuinely
    # wrong one went the other way: a Karnataka supplier charging CGST and SGST
    # to a Maharashtra buyer is tax paid to a government that is not owed it,
    # and it validated clean.
    counterparty_state = (
        gstin_service.state_code_of(invoice.counterparty_gstin or "")
        if invoice.counterparty_gstin
        else None
    )
    if is_sales:
        supplier_state = business_state
        place_of_supply = invoice.place_of_supply or counterparty_state
    else:
        supplier_state = counterparty_state
        place_of_supply = invoice.place_of_supply or business_state
    if supplier_state and place_of_supply:
        interstate = place_of_supply != supplier_state
        has_igst = (invoice.igst or ZERO) > ZERO
        has_local = (invoice.cgst or ZERO) > ZERO or (invoice.sgst or ZERO) > ZERO

        if interstate and has_local:
            add(
                "igst",
                Severity.ERROR,
                f"Inter-state supply from {supplier_state} to {place_of_supply} carries "
                "CGST/SGST; it should be IGST",
            )
        if not interstate and has_igst:
            add(
                "igst",
                Severity.ERROR,
                f"Intra-state supply in {place_of_supply} carries IGST; it should be CGST + SGST",
            )
        if not interstate and has_local and invoice.cgst != invoice.sgst:
            add(
                "cgst",
                Severity.ERROR,
                f"CGST {invoice.cgst} and SGST {invoice.sgst} must be equal on an "
                "intra-state supply",
            )

    if is_sales and not invoice.place_of_supply and not counterparty_state:
        add(
            "place_of_supply",
            Severity.ERROR,
            "Place of supply is missing and cannot be derived from a GSTIN",
        )

    return issues


def _unreadable_issue(invoice: Invoice) -> ValidationIssue:
    """Why a row with no extracted figures is blocking, in its own words.

    "Failed" and "not started yet" want different answers from the user — one
    is fixed by a re-parse or by typing the figures in, the other by waiting —
    so they are not collapsed into one message.
    """
    if invoice.status is InvoiceStatus.DUPLICATE:
        message = (
            "Reconciliation found this is a duplicate of another invoice with the "
            "same supplier and number. It is left out of the return to avoid "
            "double-declaring the supply. Correct the identifying fields or delete it."
        )
    elif invoice.status is InvoiceStatus.FAILED:
        reason = invoice.parse_error or "the extraction gave up"
        message = (
            f"Could not be read ({reason}), so it is left out of the return entirely. "
            "Re-parse it, enter the figures by hand, or delete it."
        )
    else:
        message = (
            "Still being extracted, so it is not in the return yet. Wait for the "
            "extraction to finish and validate again."
        )
    return ValidationIssue(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        field="status",
        severity=Severity.ERROR,
        message=message,
    )


def validate_period(
    db: Session,
    business: Business,
    period: str,
    *,
    invoice_type: InvoiceType = InvoiceType.SALES,
    invoices: list[Invoice] | None = None,
    unreadable: list[Invoice] | None = None,
) -> ValidationReport:
    """Validate every invoice of one direction in a period.

    Including the ones that are not in the return. :func:`_invoices` leaves out
    every row whose figures were never extracted, which is right for the
    document — a row of zeros in a return is worse than no row — but it made
    them invisible here too, and this is the only thing that says whether a
    period may be filed. A month holding three failed sales extractions came
    back ``ok: true`` with those three supplies silently absent from GSTR-1,
    from the CSV a CA checks it against, and from the totals stored when the
    filing was recorded. Under-declared output tax carries interest, and the
    product had told them the period was clean.

    So an unreadable row is reported as an error against the period rather than
    validated field by field: an invoice the parser never read has nothing to
    say about its GSTIN or its rate, and the six separate complaints that came
    out of running the field checks over one — number missing, date missing,
    no taxable value — all mean "this has not been read" and none of them said
    so.

    *invoices* is what :func:`preview` has already read, passed in rather than
    fetched again — see the note there. It must be exactly what
    :func:`_invoices` would return for the same arguments; nothing outside this
    module should be supplying it.

    *unreadable* is the complementary set — rows in UNCOUNTABLE_STATUSES —
    passed through by :func:`preview` to avoid a separate query for them.
    """
    if invoices is None:
        invoices = _invoices(db, business.id, period, invoice_type)
    if unreadable is None:
        unreadable = _unreadable_invoices(db, business.id, period, invoice_type)
    report = ValidationReport(period=period, invoice_count=len(invoices))
    for invoice in invoices:
        report.issues.extend(
            validate_invoice(invoice, business_state=business.state_code, period=period)
        )
    for invoice in unreadable:
        report.issues.append(_unreadable_issue(invoice))
    return report


# ---------------------------------------------------------------------------
# Recording that a return was filed
# ---------------------------------------------------------------------------

# The portal issues a 15-character ARN, but this is not pinned to 15. The two
# ways to be wrong here are not symmetric: too loose stores a typo, while too
# strict locks a business out of recording a filing that genuinely happened —
# and the deadline alert for that period then never clears, so the product
# nags them about a return they have already filed. The check is therefore
# only tight enough to reject something that is plainly not an ARN.
ARN_PATTERN = re.compile(r"^[0-9A-Z]{10,32}$")


class FilingNotRecordable(ValueError):
    """The filing being recorded could not have happened as described."""


def normalise_arn(arn: str | None) -> str | None:
    """Upper-case and strip an ARN, or raise if it is not one.

    The portal prints it with spaces in some acknowledgements, so whitespace is
    removed rather than rejected.
    """
    if arn is None:
        return None
    cleaned = "".join(arn.split()).upper()
    if not cleaned:
        return None
    if not ARN_PATTERN.match(cleaned):
        raise FilingNotRecordable(
            f"'{arn}' is not an ARN. The portal's acknowledgement shows a 15-character "
            "reference made up of letters and digits."
        )
    return cleaned


def record_filing(
    db: Session,
    business: Business,
    period: str,
    return_type: ReturnType,
    *,
    arn: str | None = None,
    filed_on: date | None = None,
) -> GSTRReturn:
    """Record that *return_type* for *period* was filed on the portal.

    This product prepares and exports a return; the portal is where it is
    actually submitted. Nothing here can observe that submission, so the
    business tells us — and until they do, the return is indistinguishable from
    one that was never filed. That matters beyond bookkeeping: the deadline
    alerting reads exactly this, so a filing that is never recorded is a
    business that keeps being told it is late.

    Idempotent per period and return type. Re-recording corrects the ARN or the
    date rather than filing a second time, which matches the partial unique
    index on the table — and matches what the caller means, since there is only
    ever one live GSTR-1 for a period. An omitted ARN is "not to hand" and
    leaves a stored one intact; only a supplied one replaces it. An omitted
    date on a re-record is "unchanged" for the same reason: the documented
    flow is to mark the return filed on the day and add the ARN when the
    acknowledgement arrives, and defaulting that second call to today re-dated
    every on-time filing whose ARN came after the due date — which put a late
    fee on it, and had the alerting say it was late.

    ``data`` is the return as *this application builds it now*. Immediately
    after an export — which is the flow this exists for — that is exactly what
    went to the portal. Recorded months later, against books that have since
    been corrected, it is not, and it is stored as the best available record
    rather than as proof of what was submitted. The ARN is the proof.

    A re-record leaves that snapshot alone. The first recording is the closest
    thing to what the portal received, and the portal takes no revised return
    for a period — a sale booked after filing is declared as an amendment in a
    later month. Rebuilding the snapshot while adding the ARN rewrote the
    record to say that sale was in the filed return, and the totals shown
    beside the ARN stopped agreeing with the acknowledgement they sat next to.
    """
    if return_type not in gst_calendar.DUE_DAY:
        raise FilingNotRecordable(
            f"{return_type.value} is not a return a business files. Only "
            + " and ".join(sorted(rt.value for rt in gst_calendar.DUE_DAY))
            + " can be recorded as filed."
        )

    # Before anything is mutated: a rejected ARN should leave the record it was
    # offered against exactly as it was, not half-updated in the session.
    supplied_arn = normalise_arn(arn)
    requested_on = filed_on

    existing = db.scalar(
        select(GSTRReturn).where(
            GSTRReturn.business_id == business.id,
            GSTRReturn.period == period,
            GSTRReturn.return_type == return_type,
            GSTRReturn.deleted_at.is_(None),
        )
    )

    today = gst_calendar.today_ist()
    if filed_on is None:
        # A live row here is always one this function wrote, so it carries a
        # date. It was checked when it was recorded and is re-checked below,
        # which can only pass again: "today" moves one way and the window
        # only widens.
        filed_on = today if existing is None else gst_calendar.ist_date(existing.filed_at)
    if filed_on > today:
        raise FilingNotRecordable(
            f"A filing date of {filed_on.isoformat()} is in the future."
        )

    # A period cannot be filed before it has finished — there is nothing to
    # summarise yet, and the portal does not open the return until the month is
    # over. A date inside the period is a mistyped year far more often than it
    # is anything else.
    opens_year, opens_month = gst_calendar.next_period(period).split("-")
    opens_on = date(int(opens_year), int(opens_month), 1)
    if filed_on < opens_on:
        raise FilingNotRecordable(
            f"{period} could not have been filed on {filed_on.isoformat()}: the period "
            f"had not ended. The return opens on {opens_on.isoformat()}."
        )

    record = existing or GSTRReturn(
        business_id=business.id, period=period, return_type=return_type
    )

    record.status = ReturnStatus.FILED
    # Omitting the ARN means "not to hand", not "erase the one I gave you". The
    # asymmetry is the whole point of this endpoint being idempotent: recording
    # again is how a date gets corrected, and clearing the acknowledgement as a
    # side effect of that would drop the only proof the filing happened — which
    # nothing here can re-derive, because it was issued by the portal. A wrong
    # ARN is still corrected by supplying the right one.
    if supplied_arn is not None:
        record.arn = supplied_arn
    record.filed_at = datetime.combine(filed_on, time(), tzinfo=gst_calendar.IST)
    record.due_date = datetime.combine(
        gst_calendar.due_date(period, return_type), time(), tzinfo=gst_calendar.IST
    )
    if existing is None:
        record.data = (
            build_gstr1(db, business, period)
            if return_type is ReturnType.GSTR1
            else build_gstr3b(db, business, period)
        )

        # Both returns summarise outward supplies, so both take their totals
        # from sales. The purchase side reaches GSTR-3B as input credit, which
        # is a different figure and is inside ``data``.
        totals = invoice_service.tax_summary(db, business.id, period)["sales"]
        record.invoice_count = int(totals["count"])
        record.total_taxable_value = _q(Decimal(totals["taxable_value"]))
        record.total_cgst = _q(Decimal(totals["cgst"]))
        record.total_sgst = _q(Decimal(totals["sgst"]))
        record.total_igst = _q(Decimal(totals["igst"]))
        record.total_cess = _q(Decimal(totals["cess"]))
        db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Two first recordings of one period — a double-clicked "mark filed",
        # or the owner and their CA at once — both read no row, and the partial
        # unique index lets one INSERT through. The loser was answered with the
        # generic 409 "conflicts with one that already exists", for a call this
        # endpoint promises is idempotent. The row it collided with is the
        # filing it was trying to record, so record against that instead.
        db.rollback()
        if existing is not None:
            raise
        return record_filing(
            db, business, period, return_type, arn=arn, filed_on=requested_on
        )
    db.refresh(record)
    logger.info(
        "Filing recorded",
        extra={
            "business_id": business.id,
            "period": period,
            "return_type": return_type.value,
            "arn": record.arn,
            "filed_on": filed_on.isoformat(),
            "is_update": existing is not None,
            "invoice_count": record.invoice_count,
        },
    )
    return record


def withdraw_filing(
    db: Session, business: Business, period: str, return_type: ReturnType
) -> GSTRReturn | None:
    """Take back a filing that was recorded by mistake; ``None`` if none was.

    Recording is the only way into ``filed`` and, until this, there was no way
    out. Re-recording corrects the date or the ARN, but marking the wrong month
    or the wrong return — May instead of April, a GSTR-3B for a GSTR-1 — left
    that period filed for good: its deadline alert resolved and never came
    back, its late fee stopped projecting, and the month actually unfiled was
    the one the product went quiet about. The alerting already reopens an
    alert whose filing has disappeared; nothing could make one disappear.

    A soft delete, like every other removal here: a filing record is part of
    what an assessment reads, and one taken back is still something that was
    said. The partial unique index ignores the tombstone, so recording the
    period again afterwards is an ordinary first recording.
    """
    record = db.scalar(
        select(GSTRReturn).where(
            GSTRReturn.business_id == business.id,
            GSTRReturn.period == period,
            GSTRReturn.return_type == return_type,
            GSTRReturn.status == ReturnStatus.FILED,
            GSTRReturn.deleted_at.is_(None),
        )
    )
    if record is None:
        return None
    record.soft_delete()
    db.commit()
    logger.info(
        "Filing withdrawn",
        extra={
            "business_id": business.id,
            "period": period,
            "return_type": return_type.value,
            "arn": record.arn,
        },
    )
    return record


def filed_returns(
    db: Session, business_id: int, periods: list[str] | None = None
) -> dict[tuple[str, ReturnType], GSTRReturn]:
    """Filed returns for this tenant, keyed by period and type.

    A mapping rather than a list because both callers — the alerting and the
    status endpoint — are asking "has *this* been filed", and a keyed lookup is
    what stops that becoming a query per period.
    """
    conditions = [
        GSTRReturn.business_id == business_id,
        GSTRReturn.deleted_at.is_(None),
        GSTRReturn.status == ReturnStatus.FILED,
    ]
    if periods is not None:
        if not periods:
            return {}
        conditions.append(GSTRReturn.period.in_(periods))

    # ``data`` is the whole return as built — every B2B invoice of a GSTR-1 —
    # and neither caller reads it: both ask whether and when a period was
    # filed. The ITC sweep asks it of the tenant's entire history, every night,
    # for every tenant.
    query = (
        select(GSTRReturn)
        .options(defer(GSTRReturn.data), defer(GSTRReturn.validation_errors))
        .where(*conditions)
    )
    return {(row.period, row.return_type): row for row in db.scalars(query).all()}


@dataclass(frozen=True)
class ReturnStanding:
    """Where one return, for one period, stands as of one date.

    Shared by the status endpoint and the deadline alerting so that both answer
    "is this late" the same way. They disagreed once in an earlier design, and
    an alert that contradicts the screen it links to is worse than no alert.
    """

    period: str
    return_type: ReturnType
    due_date: date
    as_of: date
    filed_on: date | None = None
    arn: str | None = None

    @property
    def filed(self) -> bool:
        return self.filed_on is not None

    @property
    def filed_late(self) -> bool:
        return self.filed_on is not None and self.filed_on > self.due_date

    @property
    def days_until_due(self) -> int:
        """Negative once the due date has passed."""
        return (self.due_date - self.as_of).days

    @property
    def overdue(self) -> bool:
        """Unfiled and past the due date. Filing late stops the clock."""
        return not self.filed and self.days_until_due < 0


def standings(
    db: Session, business_id: int, *, periods: list[str], as_of: date
) -> list[ReturnStanding]:
    """Every filable return over *periods*, oldest period first.

    One query for the lot: the caller is asking about a handful of periods
    across two return types, and a lookup per cell is six round trips to answer
    a question the dashboard asks on every load.
    """
    filed = filed_returns(db, business_id, periods)
    lines: list[ReturnStanding] = []
    for period in sorted(periods):
        for return_type in gst_calendar.DUE_DAY:
            record = filed.get((period, return_type))
            lines.append(
                ReturnStanding(
                    period=period,
                    return_type=return_type,
                    due_date=gst_calendar.due_date(period, return_type),
                    as_of=as_of,
                    filed_on=(
                        gst_calendar.ist_date(record.filed_at)
                        if record and record.filed_at
                        else None
                    ),
                    arn=record.arn if record else None,
                )
            )
    return lines


def _invoices(
    db: Session, business_id: int, period: str, invoice_type: InvoiceType
) -> list[Invoice]:
    """Filable invoices of one direction for a period, oldest first.

    Excludes every row whose figures were never extracted or that duplicates
    another row — see :data:`UNCOUNTABLE_STATUSES`. An invoice whose fields
    were never read has nothing to file, and putting a row of zeros in a
    return is worse than leaving it out and reporting it as unfiled, which
    :func:`validate_period` does. A duplicate has figures, but they belong
    to the original row and filing them double-declares the supply.
    """
    return list(
        db.scalars(
            # line_items stays: the HSN summary is built from it.
            select(Invoice)
            .options(*without_document(keep_line_items=True))
            .where(
                Invoice.business_id == business_id,
                Invoice.deleted_at.is_(None),
                Invoice.invoice_type == invoice_type,
                Invoice.period == period,
                Invoice.status.not_in(UNCOUNTABLE_STATUSES),
            )
            .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        ).all()
    )


def _unreadable_invoices(
    db: Session, business_id: int, period: str, invoice_type: InvoiceType
) -> list[Invoice]:
    """The rows :func:`_invoices` leaves out, so validation can name them."""
    return list(
        db.scalars(
            select(Invoice)
            .options(*without_document())
            .where(
                Invoice.business_id == business_id,
                Invoice.deleted_at.is_(None),
                Invoice.invoice_type == invoice_type,
                Invoice.period == period,
                Invoice.status.in_(UNCOUNTABLE_STATUSES),
            )
            .order_by(Invoice.id.asc())
        ).all()
    )


# ---------------------------------------------------------------------------
# GSTR-1 — outward supplies
# ---------------------------------------------------------------------------

def _rate_of(invoice: Invoice) -> Decimal:
    """The invoice's rate, falling back to one derived from the figures.

    A parsed invoice often carries the tax amounts but no explicit rate, and
    the portal wants a rate on every line.
    """
    if invoice.tax_rate is not None:
        return invoice.tax_rate
    taxable = invoice.taxable_value or ZERO
    if taxable <= ZERO:
        return ZERO
    tax = _tax_total(invoice) - (invoice.cess or ZERO)
    derived = (tax / taxable) * Decimal("100")
    # Snap to the nearest real slab: the arithmetic gives 17.999% where the
    # invoice plainly means 18%.
    return min(VALID_RATES, key=lambda rate: abs(rate - derived))


def _invoice_value(invoice: Invoice) -> Decimal:
    """The invoice's value including tax — what the portal calls ``val``.

    :attr:`~app.models.invoice.Invoice.invoice_value` is where the fallback now
    lives; this quantizes its answer, because a figure going into a return is
    rounded to the paisa and the property is not a formatter.

    The rule itself moved to the model because three exports had grown their own
    copy of it and the screens had none — see the property's own docstring.
    """
    return _q(invoice.invoice_value)


@dataclass(frozen=True)
class RateLine:
    """One rate-wise slice of an invoice: what the portal reports, everywhere.

    GSTR-1 is rate-wise from top to bottom. ``itms`` inside a B2B or B2CL
    invoice, the B2CS summary and the HSN summary are all keyed by rate, and an
    invoice that carries two rates has to appear in each of them twice.
    """

    rate: Decimal
    taxable_value: Decimal
    igst: Decimal
    cgst: Decimal
    sgst: Decimal
    cess: Decimal
    hsn_code: str | None = None
    quantity: Decimal = ZERO


def _allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split *total* across *weights*, to the paisa, summing back to *total*.

    The parts are rounded independently and the residual is handed to the
    largest share, so the rate-wise lines of an invoice add up to the figure
    stored on it exactly. They have to: the portal cross-foots ``itms`` against
    the invoice, and a paisa of drift is a rejected upload.
    """
    if total == ZERO:
        return [ZERO] * len(weights)
    grand = sum(weights, ZERO)
    if grand <= ZERO:
        # No rate to apportion by — every line is nil-rated. Nothing sensible
        # divides the amount, so it stays whole on the first line rather than
        # being spread on no evidence.
        return [total] + [ZERO] * (len(weights) - 1)
    parts = [_q(total * weight / grand) for weight in weights]
    largest = max(range(len(weights)), key=lambda index: weights[index])
    parts[largest] += total - sum(parts, ZERO)
    return parts


def _line_item_rate_lines(invoice: Invoice) -> list[RateLine] | None:
    """The invoice's stored breakdown as rate-wise lines, or ``None``.

    ``None`` means "there is no breakdown worth filing from", and every caller
    then falls back to treating the invoice as one line at :func:`_rate_of`.

    The bar is deliberately high, because a breakdown that does not tie to the
    invoice is worse than no breakdown: it would file rate-wise lines that add
    up to something other than the invoice they sit under, which is a rejected
    upload rather than a wrong figure. So the items are used only when every one
    of them carries a real GST rate and a readable value, and when those values
    add up to the invoice's own taxable value.

    Two or more distinct rates is the case this exists for. A breakdown on a
    single rate tells the return nothing the invoice did not already say, and
    the extraction's per-line values are less trustworthy than the invoice-level
    totals the rest of the product is built on — so it is left alone.

    A stored ``tax_rate`` also settles it. That field is only ever null or a
    human's answer: the parser is told to leave it null when the invoice mixes
    rates, and the only other way it gets set is somebody typing it in while
    looking at the paper. ``line_items`` cannot be edited at all, so a rate
    typed in over a breakdown the parser left behind is a person correcting the
    extraction, and the correction wins. What it does not do is win quietly —
    the tax then does not match the rate, which is exactly what validation says
    out loud.
    """
    if invoice.tax_rate is not None:
        return None
    items = invoice.line_items
    if not isinstance(items, list) or not items:
        return None

    groups: dict[tuple[Decimal, str | None], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            return None
        rate = invoice_parser.normalize_rate(item.get("tax_rate"))
        if rate is None:
            return None
        taxable = invoice_parser.to_money(item.get("taxable_value"), default=None)
        if taxable is None or taxable < ZERO:
            return None
        hsn = item.get("hsn_code")
        hsn = str(hsn).strip() if hsn else None
        quantity = invoice_parser.to_decimal(item.get("quantity"), default=None) or ZERO
        bucket = groups.setdefault(
            (rate, hsn or invoice.hsn_code), {"taxable": ZERO, "quantity": ZERO}
        )
        bucket["taxable"] += taxable
        bucket["quantity"] += max(ZERO, quantity)

    if len({rate for rate, _ in groups}) < 2:
        return None

    ordered = sorted(groups.items(), key=lambda entry: (entry[0][0], entry[0][1] or ""))
    taxable_total = sum((bucket["taxable"] for _, bucket in ordered), ZERO)
    invoice_taxable = _q(invoice.taxable_value or ZERO)
    if abs(taxable_total - invoice_taxable) > ARITHMETIC_TOLERANCE:
        return None

    # The lines' own values are kept — they are what the document printed — with
    # the paisa of rounding between them and the invoice given to the largest,
    # so the block foots.
    taxables = [_q(bucket["taxable"]) for _, bucket in ordered]
    largest = max(range(len(taxables)), key=lambda index: taxables[index])
    taxables[largest] += invoice_taxable - sum(taxables, ZERO)

    weights = [rate * taxable for (rate, _), taxable in zip(
        (key for key, _ in ordered), taxables, strict=True
    )]
    heads = {
        head: _allocate(_q(getattr(invoice, head) or ZERO), weights)
        for head in ("igst", "cgst", "sgst", "cess")
    }

    return [
        RateLine(
            rate=rate,
            taxable_value=taxables[index],
            igst=heads["igst"][index],
            cgst=heads["cgst"][index],
            sgst=heads["sgst"][index],
            cess=heads["cess"][index],
            hsn_code=hsn,
            quantity=bucket["quantity"],
        )
        for index, ((rate, hsn), bucket) in enumerate(ordered)
    ]


def rate_lines(invoice: Invoice) -> list[RateLine]:
    """Every rate the invoice carries, with the money split across them.

    One line for the ordinary invoice; one per rate for an invoice that mixes
    them. The mixed case used to be flattened into a single line at a rate
    derived from the totals, and the derivation is nonsense on a mixed invoice:
    ₹5,000 at 5% beside ₹5,000 at 18% is ₹1,150 of tax on ₹10,000, which
    :func:`_rate_of` reads as 11.5% and snaps to the nearest real slab, 12%. The
    return then declared ``rt: 12, txval: 10000, camt: 575, samt: 575`` — a line
    whose tax is not 12% of its value, which the portal rejects on upload.

    The parser has always asked the model for the breakdown and stored it, and
    its own schema says to leave ``tax_rate`` null "if the invoice mixes rates",
    so precisely the invoices that needed the breakdown were the ones filed
    without it.
    """
    lines = _line_item_rate_lines(invoice)
    if lines is not None:
        return lines
    return [
        RateLine(
            rate=_rate_of(invoice),
            taxable_value=_q(invoice.taxable_value or ZERO),
            igst=_q(invoice.igst or ZERO),
            cgst=_q(invoice.cgst or ZERO),
            sgst=_q(invoice.sgst or ZERO),
            cess=_q(invoice.cess or ZERO),
            hsn_code=invoice.hsn_code,
        )
    ]


def _item_blocks(lines: list[RateLine]) -> list[dict]:
    """The portal's ``itms``: one entry per rate, numbered from one.

    Folded by rate rather than emitted per line, because ``itms`` is rate-wise
    and two lines of an invoice on the same slab are one entry there however
    many HSN codes they span. The HSN summary keeps that finer grain.
    """
    by_rate: dict[Decimal, dict] = {}
    for line in lines:
        detail = by_rate.setdefault(
            line.rate,
            {"rt": float(line.rate), "txval": ZERO, "iamt": ZERO, "camt": ZERO,
             "samt": ZERO, "csamt": ZERO},
        )
        detail["txval"] += line.taxable_value
        detail["iamt"] += line.igst
        detail["camt"] += line.cgst
        detail["samt"] += line.sgst
        detail["csamt"] += line.cess
    return [
        {
            "num": number,
            "itm_det": {
                key: float(_q(value)) if isinstance(value, Decimal) else value
                for key, value in detail.items()
            },
        }
        for number, (_, detail) in enumerate(sorted(by_rate.items()), start=1)
    ]


def _is_registered(invoice: Invoice) -> bool:
    """Whether this supply goes in a B2B block or a B2C one.

    A GSTIN that does not checksum is not a registered counterparty for filing
    purposes: the portal cannot attribute the supply to anybody, so it belongs
    in B2CL or B2CS exactly as an invoice with no GSTIN at all does. Validation
    reports the bad GSTIN as an error either way — this only decides where the
    supply lands if it is filed regardless, which an export is entitled to do.

    Named rather than repeated because GSTR-1 and GSTR-3B both ask it, and the
    portal checks their answers against each other.
    """
    return bool(
        invoice.counterparty_gstin and gstin_service.is_valid(invoice.counterparty_gstin)
    )


def build_gstr1(
    db: Session,
    business: Business,
    period: str,
    *,
    invoices: list[Invoice] | None = None,
) -> dict:
    """GSTR-1 for *period* in the portal's JSON shape.

    Sales are sorted into the blocks the portal keeps separate:

    * ``b2b`` — supplies to a registered person, grouped by their GSTIN. These
      are what become the buyer's GSTR-2B, which is why the counterparty GSTIN
      has to be right: a typo here is a credit the customer cannot claim.
    * ``b2cl`` — inter-state supplies to unregistered persons above ₹2.5 lakh,
      reported invoice by invoice.
    * ``b2cs`` — everything else to unregistered persons, summarised by place
      of supply and rate rather than listed.
    * ``hsn`` — the rate-wise summary by HSN, which the portal requires
      alongside the invoice data.

    *invoices* is :func:`preview`'s single read of the sales side; see the note
    there.
    """
    if invoices is None:
        invoices = _invoices(db, business.id, period, InvoiceType.SALES)

    b2b: dict[str, list[dict]] = {}
    b2cl: dict[str, list[dict]] = {}
    b2cs: dict[tuple[str, Decimal], dict] = {}
    hsn: dict[tuple[str, Decimal], dict] = {}

    threshold = b2cl_threshold(period)

    for invoice in invoices:
        counterparty_state = gstin_service.state_code_of(invoice.counterparty_gstin or "")
        place_of_supply = invoice.place_of_supply or counterparty_state or business.state_code
        lines = rate_lines(invoice)
        interstate = place_of_supply != business.state_code
        # Derived rather than read straight off the row: which block a B2C
        # supply belongs in turns on this number, and a stored zero would put a
        # ₹3 lakh invoice in the summary that exists for small ones.
        value = _invoice_value(invoice)

        if _is_registered(invoice):
            b2b.setdefault(invoice.counterparty_gstin or "", []).append(
                {
                    "inum": invoice.invoice_number or "",
                    "idt": to_portal_date(invoice.invoice_date),
                    "val": float(value),
                    "pos": place_of_supply,
                    "rchrg": "Y" if invoice.reverse_charge else "N",
                    "inv_typ": "R",  # Regular. SEZ and deemed export are not modelled yet.
                    "itms": _item_blocks(lines),
                }
            )
        elif interstate and value > threshold:
            b2cl.setdefault(place_of_supply, []).append(
                {
                    "inum": invoice.invoice_number or "",
                    "idt": to_portal_date(invoice.invoice_date),
                    "val": float(value),
                    "itms": _item_blocks(lines),
                }
            )
        else:
            # Rate-wise, so an invoice that mixes rates lands in as many B2CS
            # buckets as it has rates. Summarised at one blended rate it was a
            # bucket whose tax is not its rate applied to its value, which is
            # the one thing the portal checks about this block.
            for line in lines:
                bucket = b2cs.setdefault(
                    (place_of_supply, line.rate),
                    {
                        "sply_ty": "INTER" if interstate else "INTRA",
                        "typ": "OE",  # Other than e-commerce.
                        "pos": place_of_supply,
                        "rt": float(line.rate),
                        "txval": ZERO,
                        "iamt": ZERO,
                        "camt": ZERO,
                        "samt": ZERO,
                        "csamt": ZERO,
                    },
                )
                bucket["txval"] += line.taxable_value
                bucket["iamt"] += line.igst
                bucket["camt"] += line.cgst
                bucket["samt"] += line.sgst
                bucket["csamt"] += line.cess

        for line in lines:
            if not line.hsn_code:
                continue
            entry = hsn.setdefault(
                (line.hsn_code, line.rate),
                {
                    "hsn_sc": line.hsn_code,
                    "uqc": "NOS",  # Not extracted yet; NOS is the portal's catch-all.
                    "qty": ZERO,
                    "rt": float(line.rate),
                    "txval": ZERO,
                    "iamt": ZERO,
                    "camt": ZERO,
                    "samt": ZERO,
                    "csamt": ZERO,
                },
            )
            entry["qty"] += line.quantity
            entry["txval"] += line.taxable_value
            entry["iamt"] += line.igst
            entry["camt"] += line.cgst
            entry["samt"] += line.sgst
            entry["csamt"] += line.cess

    def _floats(bucket: dict) -> dict:
        return {
            key: float(_q(value)) if isinstance(value, Decimal) else value
            for key, value in bucket.items()
        }

    document: dict = {
        "gstin": business.gstin,
        "fp": to_portal_period(period),
        "version": GSTR1_VERSION,
        "hash": "hash",  # The offline utility computes the real one on upload.
    }
    if b2b:
        document["b2b"] = [
            {"ctin": ctin, "inv": invs} for ctin, invs in sorted(b2b.items())
        ]
    if b2cl:
        document["b2cl"] = [
            {"pos": pos, "inv": invs} for pos, invs in sorted(b2cl.items())
        ]
    if b2cs:
        document["b2cs"] = [_floats(bucket) for _, bucket in sorted(b2cs.items())]
    if hsn:
        document["hsn"] = {
            "data": [
                {"num": index, **_floats(entry)}
                for index, (_, entry) in enumerate(sorted(hsn.items()), start=1)
            ]
        }
    return document


# ---------------------------------------------------------------------------
# GSTR-3B — the monthly summary and payment
# ---------------------------------------------------------------------------

def build_gstr3b(
    db: Session,
    business: Business,
    period: str,
    *,
    as_of: date | None = None,
    invoices: list[Invoice] | None = None,
) -> dict:
    """Pre-fill GSTR-3B for *period* from sales, purchases and the last run.

    Table 4 is filled from the reconciled ITC position rather than from the
    purchase register, because 4(A) is credit *available* and only GSTR-2B
    establishes that. The reversals computed under Rules 37, 42 and 43 land in
    4(B), and 4(C) is the net — which is the figure that actually reduces the
    cash payable.

    Table 3.1 takes one line from the purchase side: 3.1(d), the inward
    supplies the buyer owes the tax on. It used to take none, and a business
    paying a goods transport agency, a lawyer or an unregistered landlord filed
    a 3B that declared no reverse-charge liability at all. That tax cannot be
    settled from the credit ledger — s.49(4) lets credit pay "output tax", and
    s.2(82) puts reverse charge outside it — so the omission is cash the
    business did not pay, with interest running on it from the due date. The
    credit it earns comes back at 4(A)(3), which is why the round trip is
    close to free over the month and the missing declaration was invisible.

    Rule 37 is a clock — credit reverses 180 days after an invoice date — and a
    clock has to be told which day the return is a statement about. Reading it
    off *today* made a closed period's return move: a business that generated
    its January 3B in February and again in March got two different documents,
    the second one reversing credit on invoices that had not yet crossed 180
    days when January ended, and on invoices dated months *after* January that
    could not belong to its return at all. Anchored to the close of the period,
    so re-generating an old return reproduces it.

    *as_of* overrides that anchor, for a caller reconstructing what the return
    would have said on some other day. The default is capped at today, so
    previewing a month still in progress does not reverse credit early.

    Anchoring the clock is only half of it: the reversal in 4(B) is what
    lapsed *during* this period, not everything standing at its close. Rule 37
    is paid once, in the return for the month the 180 days ran out, and
    re-availed when the supplier is paid. Taking the whole standing exposure
    reversed the same invoice again in every return that followed it — April,
    then May, then June — so a business filing four months gave back four
    times what the rule asks for, and each of those returns still reproduced
    itself exactly, which is what made it invisible.

    And the re-availment is the other half again. The reversal was declared and
    the credit never came back: paying the supplier merely stopped the reversal
    recurring, so an invoice that once crossed 180 days lost its whole ITC for
    good. It is claimed here in 4(A) — see :func:`app.services.itc.rule_37_reavailment`.
    """
    if as_of is None:
        as_of = min(gst_calendar.period_end(period), gst_calendar.today_ist())
    summary = itc_service.summarise(db, business.id, period, as_of=as_of)
    # *invoices* is :func:`preview`'s single read of the sales side; see there.
    sales = invoices if invoices is not None else _invoices(
        db, business.id, period, InvoiceType.SALES
    )

    outward_taxable = ZERO
    outward_exempt = ZERO
    interstate_unregistered: dict[str, dict] = {}
    for invoice in sales:
        taxable = _q(invoice.taxable_value or ZERO)
        # A reverse-charge sale goes to 3.1(c) with the supplies this business
        # pays no tax on, which is what it is to the supplier: the recipient
        # pays under s.9(3)/9(4) and declares it at their own 3.1(d). Left in
        # 3.1(a) its value sat beside a tax figure that (rightly) leaves its tax
        # out — see ``itc._outward_tax_and_turnover`` — and before that, the
        # tax was paid here as well as by the customer.
        if invoice.reverse_charge or _tax_total(invoice) == ZERO:
            outward_exempt += taxable
            continue
        outward_taxable += taxable

        # Table 3.2: inter-state supplies to unregistered persons, by state.
        #
        # "Unregistered" is decided exactly as :func:`build_gstr1` decides it,
        # and that is the whole point of the helper: the portal cross-checks
        # 3.2 against the B2CL and B2CS blocks of the GSTR-1 for the same
        # period, so the two returns have to agree on which supplies are B2C.
        # Testing only for a *present* GSTIN here made them disagree on the one
        # invoice where it matters — a customer GSTIN that does not checksum is
        # filed as B2C in GSTR-1, because a buyer the portal cannot identify
        # cannot be given credit, and was silently missing from 3.2.
        counterparty_state = gstin_service.state_code_of(invoice.counterparty_gstin or "")
        place_of_supply = invoice.place_of_supply or counterparty_state or business.state_code
        if not _is_registered(invoice) and place_of_supply != business.state_code:
            bucket = interstate_unregistered.setdefault(
                place_of_supply, {"pos": place_of_supply, "txval": ZERO, "iamt": ZERO}
            )
            bucket["txval"] += taxable
            bucket["iamt"] += invoice.igst or ZERO

    output = summary.output_tax
    # 4(A)(5), "All other ITC": this period's own credit, the month's slice of
    # capital-goods credit under Rule 43, and credit an earlier return gave up
    # under Rule 37 that this month's payment to the supplier brings back. The
    # last of those had nowhere to go — the reversal was declared and the
    # re-availment the proviso to s.16(2)(d) allows never was, so paying a
    # supplier late cost the whole of that invoice's credit permanently.
    available = (
        summary.available
        + summary.proportionate.capital_credit_this_month
        + summary.rule_37_reavailment
    )
    reversal = summary.total_reversal
    reverse_charge = summary.reverse_charge

    return {
        "gstin": business.gstin,
        "ret_period": to_portal_period(period),
        # 3.1(a): outward taxable supplies, other than zero-rated/nil/exempt.
        "sup_details": {
            "osup_det": {
                "txval": float(_q(outward_taxable)),
                "iamt": float(_q(output.igst)),
                "camt": float(_q(output.cgst)),
                "samt": float(_q(output.sgst)),
                "csamt": float(_q(output.cess)),
            },
            # 3.1(c): nil-rated and exempt outward supplies.
            "osup_nil_exmp": {"txval": float(_q(outward_exempt))},
            # 3.1(d): inward supplies on which *we* owe the tax. The only line
            # of table 3.1 fed by purchases rather than sales, and the one that
            # was missing: a business paying freight, legal fees or rent to an
            # unregistered landlord filed a 3B declaring none of it. The tax is
            # payable in cash whatever the credit ledger holds, so the shortfall
            # is real money and interest runs on it from the due date.
            "isup_rev": {
                "txval": float(_q(reverse_charge.taxable_value)),
                "iamt": float(_q(reverse_charge.tax.igst)),
                "camt": float(_q(reverse_charge.tax.cgst)),
                "samt": float(_q(reverse_charge.tax.sgst)),
                "csamt": float(_q(reverse_charge.tax.cess)),
            },
        },
        # 3.2: of the above, supplies to unregistered persons in other states.
        "inter_sup": {
            "unreg_details": [
                {
                    "pos": bucket["pos"],
                    "txval": float(_q(bucket["txval"])),
                    "iamt": float(_q(bucket["iamt"])),
                }
                for _, bucket in sorted(interstate_unregistered.items())
            ]
        },
        # 4: eligible ITC — available, reversed, and the net of the two.
        "itc_elg": {
            "itc_avl": [
                {
                    "ty": "OTH",  # All other ITC; imports and ISD are not modelled yet.
                    "iamt": float(_q(available.igst)),
                    "camt": float(_q(available.cgst)),
                    "samt": float(_q(available.sgst)),
                    "csamt": float(_q(available.cess)),
                },
                # 4(A)(3): the credit side of 3.1(d). Declared as its own row
                # because the portal keeps it as one, and because it is the
                # half that makes the reverse-charge round trip cost nothing
                # over the month — claiming it in "all other ITC" would file a
                # 3.1(d) liability with no visible credit against it, which is
                # the shape of a return that invites a query.
                {
                    "ty": "ISRC",  # Inward supplies liable to reverse charge.
                    "iamt": float(_q(reverse_charge.credit.igst)),
                    "camt": float(_q(reverse_charge.credit.cgst)),
                    "samt": float(_q(reverse_charge.credit.sgst)),
                    "csamt": float(_q(reverse_charge.credit.cess)),
                },
            ],
            "itc_rev": [
                {
                    "ty": "RUL",  # Reversal under rules 37, 42 and 43.
                    "iamt": float(_q(reversal.igst)),
                    "camt": float(_q(reversal.cgst)),
                    "samt": float(_q(reversal.sgst)),
                    "csamt": float(_q(reversal.cess)),
                }
            ],
            "itc_net": {
                "iamt": float(_q(summary.net_available.igst)),
                "camt": float(_q(summary.net_available.cgst)),
                "samt": float(_q(summary.net_available.sgst)),
                "csamt": float(_q(summary.net_available.cess)),
            },
        },
        # Not part of the portal's schema: what the set-off leaves to pay in
        # cash, so the screen can show it without recomputing.
        "gstbot_set_off": summary.set_off.as_dict(),
        # Also ours. The set-off above settles output tax only, because credit
        # may not settle a reverse-charge liability — so the cash a business
        # actually has to find this month is the two added together, and it is
        # given here rather than left to a caller to remember.
        "gstbot_reverse_charge": reverse_charge.as_dict(),
        "gstbot_cash_payable": str(summary.cash_payable),
    }


# ---------------------------------------------------------------------------
# Preview — a return and its validation, from one read of the period
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FilingPreview:
    """A generated return with the validation that ran over the same rows."""

    period: str
    return_type: str
    document: dict
    validation: ValidationReport


def preview(
    db: Session,
    business: Business,
    period: str,
    return_type: ReturnType,
    *,
    as_of: date | None = None,
) -> FilingPreview:
    """Build a return and validate its period, reading the sales side once.

    Both halves want the same rows. ``build_gstr1`` needs them to fill the
    B2B/B2CL/B2CS blocks, ``build_gstr3b`` to fill table 3.1 and 3.2, and
    ``validate_period`` to check every field on each of them — and each was
    calling :func:`_invoices` for itself, so a preview issued the identical
    query twice and hydrated the same period into two sets of ORM objects.

    That is not a rounding error at the sizes this endpoint is asked about. On
    a period of 3,000 sales invoices the two halves cost 80 ms each and the
    duplicated read is 33 ms of that — a fifth of the whole response, spent
    fetching rows already sitting in the session.

    Passing the list rather than caching inside :func:`_invoices` because a
    cache keyed on the session would have to guess when an upload or a
    reconciliation had invalidated it, and guessing wrong means a return built
    from stale invoices. Here the read and both uses of it are three lines
    apart, so the list cannot go stale between them.

    The validation is over sales in both cases. GSTR-3B is a summary with no
    invoice detail of its own, and what would stop it being filed is the same
    unreadable or malformed sales rows that would stop the GSTR-1.
    """
    invoices = _invoices(db, business.id, period, InvoiceType.SALES)
    unreadable = _unreadable_invoices(db, business.id, period, InvoiceType.SALES)
    document = (
        build_gstr3b(db, business, period, as_of=as_of, invoices=invoices)
        if return_type is ReturnType.GSTR3B
        else build_gstr1(db, business, period, invoices=invoices)
    )
    return FilingPreview(
        period=period,
        return_type=return_type.value,
        document=document,
        validation=validate_period(
            db, business, period, invoices=invoices, unreadable=unreadable,
        ),
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

CSV_COLUMNS = (
    "invoice_number",
    "invoice_date",
    "counterparty_gstin",
    "counterparty_name",
    "place_of_supply",
    "hsn_code",
    "tax_rate",
    "taxable_value",
    "cgst",
    "sgst",
    "igst",
    "cess",
    "total_value",
    "reverse_charge",
    "status",
)


def to_csv(db: Session, business: Business, period: str, invoice_type: InvoiceType) -> str:
    """A period's invoices as CSV, for a human or a CA to check.

    ``\\r\\n`` line endings and quoting on every non-numeric field: this is
    opened in Excel far more often than it is parsed, and Excel is where a
    stray comma in a trade name silently shifts a row.

    Being opened in Excel is also why every text column goes through
    :func:`~app.core.sanitize.csv_safe`. The fields here are free text off an
    uploaded invoice, and Excel runs a cell that starts with ``=``. The numeric
    columns are deliberately not put through it: this application formats them,
    and a credit note's leading ``-`` is a minus sign.

    ``total_value`` is derived by :func:`_invoice_value` rather than read off
    the column, for the reason that function exists: the stored total defaults
    to zero and is only filled when the parser found a grand-total *label* on
    the document, so an invoice whose total was printed as "Amount Payable"
    carries a stored zero. Read straight off the row, this column reported a
    real supply as one worth nothing — and reported it in the one artefact a CA
    opens to check a period before it is filed, while ``/filing/export/gstr1.json``
    for the same period carried the right figure all along. Two exports of one
    month disagreeing about what an invoice is worth is worse than either being
    wrong on its own, because the CSV is what gets believed.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\r\n"
    )
    writer.writeheader()
    for invoice in _invoices(db, business.id, period, invoice_type):
        writer.writerow(
            {
                "invoice_number": csv_safe(invoice.invoice_number),
                "invoice_date": to_portal_date(invoice.invoice_date) or "",
                "counterparty_gstin": csv_safe(invoice.counterparty_gstin),
                "counterparty_name": csv_safe(invoice.counterparty_name),
                "place_of_supply": csv_safe(invoice.place_of_supply),
                "hsn_code": csv_safe(invoice.hsn_code),
                "tax_rate": str(invoice.tax_rate) if invoice.tax_rate is not None else "",
                "taxable_value": str(_q(invoice.taxable_value or ZERO)),
                "cgst": str(_q(invoice.cgst or ZERO)),
                "sgst": str(_q(invoice.sgst or ZERO)),
                "igst": str(_q(invoice.igst or ZERO)),
                "cess": str(_q(invoice.cess or ZERO)),
                "total_value": str(_q(_invoice_value(invoice))),
                "reverse_charge": "Y" if invoice.reverse_charge else "N",
                "status": invoice.status.value,
            }
        )
    return buffer.getvalue()


def filename_for(business: Business, period: str, kind: str, extension: str) -> str:
    """A download name that says what the file is without being opened."""
    gstin = business.gstin or f"biz{business.id}"
    return f"{kind}_{gstin}_{to_portal_period(period)}.{extension}"
