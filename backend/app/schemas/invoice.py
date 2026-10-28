"""Request/response models for invoices."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.invoice import InvoiceSource, InvoiceStatus, InvoiceType
from app.models.mixins import MONEY_MAX
from app.services import gst_calendar
from app.services import gstin as gstin_service
from app.services.gst_calculator import quoted_rate
from app.services.invoice_parser import VALID_TAX_RATES


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    supplier_id: int | None = None
    invoice_type: InvoiceType
    status: InvoiceStatus
    source: InvoiceSource

    counterparty_gstin: str | None = None
    counterparty_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    period: str | None = None
    place_of_supply: str | None = None
    hsn_code: str | None = None

    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total_value: Decimal
    # What the invoice is *worth*, as every export values it — the stored total
    # where the extractor found one, and taxable value plus tax where it did
    # not. ``total_value`` above is the raw column and stays that way, because
    # it is what a reviewer edits and what validation cross-foots; this is the
    # figure a screen should print. Served rather than left to each client to
    # derive, so the register and the return it produces cannot disagree about
    # what one invoice came to. See ``Invoice.invoice_value``.
    invoice_value: Decimal
    tax_rate: Decimal | None = None
    itc_eligible: bool
    reverse_charge: bool
    # What the Rule 37 and Rule 43 reversals are computed from. Returned so the
    # review screen can show why an invoice is on the reversal list, and so a
    # client can tell "not paid" from "we never asked".
    paid_at: date | None = None
    is_capital_good: bool = False

    source_filename: str | None = None
    parsed_with: str | None = None
    extraction_confidence: float | None = None
    parse_error: str | None = None
    created_at: datetime
    # No ``total_tax`` here. It was a plain ``@property``, which Pydantic does
    # not serialize and no caller ever read: absent from ``model_fields``, from
    # ``model_computed_fields`` and from the OpenAPI schema, so every client
    # summing the four heads itself was not working around it — the field was
    # never on the wire. ``Invoice.total_tax`` on the ORM model is the real one
    # and is what the services use. Restoring this would mean
    # ``@computed_field``, and a new response field is an API change to make
    # deliberately rather than by fixing a property nobody could see.


class InvoiceDetailOut(InvoiceOut):
    """One invoice, with everything the review screen needs.

    ``warnings`` is lifted out of the stored extraction rather than being its
    own column: it is derived from the parse, and a reviewer needs it next to
    the numbers it is about.
    """

    line_items: list[dict] | None = None
    extraction: dict | None = None
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_invoice(cls, invoice) -> InvoiceDetailOut:
        detail = cls.model_validate(invoice)
        extraction = invoice.extraction or {}
        warnings = extraction.get("warnings") or []
        return detail.model_copy(
            update={"warnings": [str(w) for w in warnings] if isinstance(warnings, list) else []}
        )


class InvoiceListOut(BaseModel):
    items: list[InvoiceOut]
    total: int
    limit: int
    offset: int


class InvoiceUploadResponse(BaseModel):
    """What the upload endpoint returns.

    ``queued`` tells the client whether extraction has already happened
    (inline mode) or is still to come (a worker picked it up), so the UI knows
    whether to poll rather than guessing from the status.
    """

    invoice: InvoiceDetailOut
    queued: bool
    message: str


class InvoiceBulkUploadItemOut(BaseModel):
    """One file's outcome within a bulk upload.

    A batch never fails as a whole — see ``POST /invoices/bulk`` — so every
    file gets one of these rather than the request getting one status code for
    fifty documents. ``filename`` is what the caller sent, not what was stored,
    so a rejection can be matched back to the file that caused it without a
    second round trip.
    """

    filename: str
    accepted: bool
    invoice: InvoiceDetailOut | None = None
    queued: bool = False
    error: str | None = None
    # Set alongside a duplicate error, so a client can link straight to the
    # invoice already on file instead of making the user search for it.
    duplicate_of_invoice_id: int | None = None


class InvoiceBulkUploadResponse(BaseModel):
    """The outcome of a whole batch: one line per file, plus the totals."""

    total: int
    accepted: int
    rejected: int
    items: list[InvoiceBulkUploadItemOut]


class InvoiceUpdate(BaseModel):
    """Reviewer corrections to an extracted invoice.

    Every field is optional and unset fields are left alone: a user fixing a
    misread GSTIN must not blank the amounts by omission.

    Omitted and ``null`` are different things here. Omitting a field leaves it
    alone; sending ``null`` clears it, which is how a misread GSTIN or date is
    taken back off an invoice. The money and the boolean flags have no cleared
    state — an invoice always carries a figure for every head, zero included —
    so a ``null`` there is refused rather than written.

    ``paid_at`` is the exception among the dates: clearing it is meaningful, and
    means "not paid after all". Under Rule 37 that is what puts an invoice back
    on the 180-day clock, so it has to be expressible.
    """

    # The same generous bound as ``RegisterRequest.gstin``, and for the same
    # reason: the validator below normalises away the spacing people paste out
    # of a registration certificate, so refusing "27 AAPFU0939F 1ZV" on length
    # before that runs would be a worse error than the one it is trying to give.
    #
    # The validator already refuses everything that is not a real GSTIN, so this
    # changes no verdict. It stops an arbitrarily long value reaching the parse
    # and the error that quotes it back, and it was the last string the API
    # accepted anywhere with no declared bound.
    counterparty_gstin: str | None = Field(default=None, max_length=32)
    counterparty_name: str | None = Field(default=None, max_length=255)
    invoice_number: str | None = Field(default=None, max_length=64)
    invoice_date: date | None = None
    place_of_supply: str | None = Field(default=None, max_length=2)
    # Room for the dotted tariff form ("8471.30.10"); `_hsn_digits` holds it to 8 digits.
    hsn_code: str | None = Field(default=None, max_length=12)
    # Bounded above as well as below. ``ge=0`` alone let a correction of
    # ``1E+100`` through with a 200: the column took it on SQLite, and every
    # screen that totals the period then raised ``InvalidOperation`` out of the
    # quantize that rounds to paise — the dashboard, the ITC summary and the
    # GSTR-3B preview all 500ing on a read, because of a write that had said it
    # was fine. ``MONEY_MAX`` is what ``Numeric(16, 2)`` actually holds, so the
    # refusal happens next to the box the figure was typed into.
    taxable_value: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    cgst: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    sgst: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    igst: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    cess: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    total_value: Decimal | None = Field(default=None, ge=0, le=MONEY_MAX)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    itc_eligible: bool | None = None
    reverse_charge: bool | None = None

    # ---- The two facts the reversal rules turn on ----
    # Rule 37 reverses the credit on a purchase left unpaid 180 days past its
    # invoice date, and Rule 43 spreads a capital good's credit over sixty
    # months instead of claiming it in the month of purchase. Both are
    # bookkeeping facts about the invoice rather than anything a document says,
    # so a person is the only possible source for them.
    paid_at: date | None = None
    is_capital_good: bool | None = None

    @field_validator("paid_at")
    @classmethod
    def _not_in_the_future(cls, v: date | None) -> date | None:
        """Refuse a payment date that has not arrived yet.

        Not pedantry: an unpaid invoice past 180 days reverses its credit, and a
        ``paid_at`` in the future takes it off that list. A mistyped year is
        therefore an under-reported reversal in GSTR-3B — over-claimed credit,
        with interest running on it — and it would sit there silently until the
        typo happened to come due.

        Measured against the Indian date, like every other deadline here.
        """
        if v is not None and v > gst_calendar.today_ist():
            raise ValueError(
                f"A payment date of {v.isoformat()} is in the future. Enter the "
                "date the supplier was actually paid."
            )
        return v

    @field_validator("invoice_date")
    @classmethod
    def _a_date_an_invoice_could_carry(cls, v: date | None) -> date | None:
        """Refuse an invoice date outside the span a GST invoice can fall in.

        The filing period is derived from this field, so a slipped year does
        not produce a wrong number on a return — it takes the invoice out of
        every return there is. A sale corrected to 2099 left the April GSTR-1
        empty, and the validation endpoint then reported that return
        ``ok: true`` with ``invoice_count: 0`` and no issues at all, because
        every check downstream is scoped to a period and the invoice was no
        longer in one. That is under-declared output tax, arrived at silently,
        on the screen whose whole job is to say whether a return is safe to
        file.

        Both ends are the same typo. Nothing before GST commenced can be a GST
        invoice, and nothing dated after today has been issued yet.
        """
        if v is None or gst_calendar.is_filable_invoice_date(v):
            return v
        raise ValueError(
            f"An invoice date of {v.isoformat()} is not one an invoice can carry. "
            f"Expected a date between {gst_calendar.GST_COMMENCEMENT.isoformat()}, "
            f"when GST commenced, and today."
        )

    @field_validator("tax_rate")
    @classmethod
    def _a_gst_slab(cls, v: Decimal | None) -> Decimal | None:
        """A rate GST actually levies, not just a number from 0 to 100.

        The parser has only ever kept a rate on :data:`VALID_TAX_RATES`, but a
        correction took any figure in range, so ``17`` or ``12.5`` was stored and
        exported on the GSTR-1 line as its ``rt`` — a value the portal refuses,
        on the return this product exists to get right.
        """
        if v is None or v in VALID_TAX_RATES:
            return v
        allowed = ", ".join(f"{r.normalize():f}" for r in sorted(VALID_TAX_RATES))
        raise ValueError(f"{quoted_rate(v)}% is not a GST rate. Use one of: {allowed}")

    @field_validator("hsn_code")
    @classmethod
    def _hsn_digits(cls, v: str | None) -> str | None:
        """4 to 8 digits, as the portal takes them; blank clears the field.

        Length alone admitted "abcd" or "N/A", which then went out in the
        GSTR-1 HSN summary. The dotted form printed on tariff schedules
        (``8471.30``) is read as its digits.
        """
        if v is None or not v.strip():
            return None
        digits = v.strip().replace(".", "").replace(" ", "")
        if not digits.isascii() or not digits.isdigit() or not 4 <= len(digits) <= 8:
            raise ValueError("An HSN/SAC code is 4 to 8 digits")
        return digits

    @field_validator("invoice_number")
    @classmethod
    def _invoice_number_not_blank(cls, v: str | None) -> str | None:
        """Surrounding space trimmed, and an all-space number cleared.

        Stored as typed, "   " was an invoice number duplicate detection keyed
        on and GSTR-1 exported as ``inum``; " INV-1 " never matched "INV-1".
        """
        if v is None:
            return None
        return v.strip() or None

    @field_validator("counterparty_gstin")
    @classmethod
    def _valid_gstin(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            return gstin_service.parse(v).gstin
        except gstin_service.InvalidGSTIN as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("place_of_supply")
    @classmethod
    def _real_state_code(cls, v: str | None) -> str | None:
        """Refuse a place of supply that is not a state GST assigns.

        This field is a code, not free text: it decides the IGST-versus-CGST+SGST
        split on the invoice and it is copied verbatim into ``pos`` on every
        GSTR-1 line. The extractor has always checked it against
        :data:`~app.services.gstin.STATE_CODES` — a correction did not, and it
        is the one path a person types into. ``ZZ`` was stored, validated clean
        (the split check only compares two codes for equality, and ``ZZ`` is
        unequal to everything), and filed, where the portal rejects the upload.

        A single digit is padded rather than refused. ``7`` for Delhi is what a
        person types and ``07`` is what the portal wants, and turning one into
        the other is not a decision worth putting in front of a reviewer.
        """
        if v is None:
            return None
        code = v.strip()
        if not code:
            return None
        if code.isdigit():
            code = code.zfill(2)
        if code not in gstin_service.STATE_CODES:
            raise ValueError(
                f"'{v}' is not a GST state code. Expected one of "
                f"{min(gstin_service.STATE_CODES)}-38, 97 or 99."
            )
        return code

    @field_validator("hsn_code")
    @classmethod
    def _real_hsn(cls, v: str | None) -> str | None:
        """Refuse an HSN/SAC that is not the shape the portal accepts.

        4, 6 or 8 digits, which is exactly what
        :func:`~app.services.filing.validate_invoice` calls an error on the way
        out. Saying it here as well is not duplication: caught at the filing
        step it is a line in a report someone reads before an upload, caught
        here it is a message next to the box while the paper is still in the
        reviewer's hand.
        """
        if v is None:
            return None
        code = v.strip()
        if not code:
            return None
        if not code.isdigit() or len(code) not in (4, 6, 8):
            raise ValueError(
                f"'{v}' is not an HSN or SAC code. The portal takes 4, 6 or 8 digits."
            )
        return code

    @field_validator(
        "taxable_value",
        "cgst",
        "sgst",
        "igst",
        "cess",
        "total_value",
        "itc_eligible",
        "reverse_charge",
        "is_capital_good",
    )
    @classmethod
    def _not_cleared(cls, v, info):
        """Refuse an explicit ``null`` on a field the invoice must always have.

        These columns are NOT NULL. Written through, a ``null`` reached the
        database and came back as an integrity error the API reported as 409
        "that record conflicts with one that already exists" — which is a
        statement about duplicates, and sends a reviewer looking for an invoice
        that does not exist. A form that clears a tax box is the ordinary way
        to arrive here, so it has to say what is actually wrong.
        """
        if v is None:
            raise ValueError(
                # No field name: the form puts the field's label in front of
                # this, and naming it here printed "Taxable value:
                # taxable_value cannot be cleared".
                "This cannot be left empty. Enter 0 if the amount is nil, or "
                "leave the field as it was."
            )
        return v
