"""Invoice upload, listing, review and correction."""
from __future__ import annotations

import logging
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_business, require_writer
from app.core.params import Offset, RowId
from app.core.rate_limit import RateLimit
from app.core.sanitize import safe_filename, search_pattern
from app.models.business import Business
from app.models.invoice import (
    UNREADABLE_STATUSES,
    Invoice,
    InvoiceSource,
    InvoiceStatus,
    InvoiceType,
    without_document,
)
from app.schemas.invoice import (
    InvoiceBulkUploadItemOut,
    InvoiceBulkUploadResponse,
    InvoiceDetailOut,
    InvoiceListOut,
    InvoiceOut,
    InvoiceUpdate,
    InvoiceUploadResponse,
)
from app.services import gst_calendar, invoice_service
from app.services.reconciliation import COMPARED_FIELDS

logger = logging.getLogger(__name__)

# The statuses a reconciliation writes, and the fields it reached them from:
# the two the row is found by, the one that fixes which period's run judges
# it, and the money it compares.
VERDICT_STATUSES = frozenset(
    {InvoiceStatus.MATCHED, InvoiceStatus.MISMATCHED, InvoiceStatus.MISSING_IN_2B,
     InvoiceStatus.DUPLICATE}
)
RECONCILED_FIELDS = frozenset(
    {"counterparty_gstin", "invoice_number", "invoice_date", *COMPARED_FIELDS}
)

router = APIRouter(prefix="/invoices", tags=["invoices"])

# An upload costs a model call and a write; 60 a minute is a comfortable
# ceiling for the drag-a-folder-in case and a floor under the cost of abuse.
_upload_limit = RateLimit("invoice_upload", "60/minute")
# Re-extraction is the same model call with none of the plan accounting, so it
# gets the tighter budget of the two.
_reparse_limit = RateLimit("invoice_reparse", "20/minute")
_read_limit = RateLimit("invoice_read", "240/minute")
_write_limit = RateLimit("invoice_write", "120/minute")

InvoiceSort = Literal[
    "date_desc", "date_asc",
    "value_desc", "value_asc",
    "number_desc", "number_asc",
]

# What a row is worth, in SQL. Mirrors ``Invoice.invoice_value``: the stored
# total where the extractor found one, the taxable value plus tax where it did
# not — because the column defaults to zero on a bare "Total:" the heuristic
# pattern misses, and sorting by that column would put a ₹5,31,000 invoice
# after every one that extraction happened to value correctly.
_VALUE_EXPR = case(
    (Invoice.total_value != 0, Invoice.total_value),
    else_=func.coalesce(Invoice.taxable_value, 0)
    + Invoice.cgst + Invoice.sgst + Invoice.igst + Invoice.cess,
)

# Nulls sort last regardless of direction on both of the nullable columns here.
# A document nothing could read a date or number off is missing that fact, not
# holding the smallest possible one — sorting oldest-first should not open on a
# page of invoices with no date, and sorting Z-to-A should not close on them
# either.
_SORTS: dict[str, tuple] = {
    "date_desc": (Invoice.invoice_date.desc().nulls_last(),),
    "date_asc": (Invoice.invoice_date.asc().nulls_last(),),
    "value_desc": (_VALUE_EXPR.desc(),),
    "value_asc": (_VALUE_EXPR.asc(),),
    "number_desc": (Invoice.invoice_number.desc().nulls_last(),),
    "number_asc": (Invoice.invoice_number.asc().nulls_last(),),
}

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic",
    "text/plain", "text/csv", "application/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
# application/octet-stream is deliberately absent. Browsers send it for a file
# they cannot type, and then the extension has to decide — which is what the
# check below does for any type not listed. Listing it made it a pass on its
# own, so bill.exe, sent untyped, was stored as an invoice.
ALLOWED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".txt", ".csv", ".xlsx", ".xlsm", ".xls",
)

# Spelt out in the refusal rather than left for the caller to guess. What
# someone does next is convert the file or pick a different one, and neither is
# a decision they can make from "unsupported". Derived from the tuple above so
# a format added to one is in the other.
ACCEPTED_LABEL = ", ".join(ext.removeprefix(".").upper() for ext in ALLOWED_EXTENSIONS)


def _owned_invoice(db: Session, business: Business, invoice_id: int) -> Invoice:
    """Fetch an invoice, 404ing on anything outside the caller's tenant.

    404 rather than 403 for another tenant's row: a 403 would confirm that the
    id exists, which is enough to probe a competitor's invoice volume.
    """
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id,
            Invoice.deleted_at.is_(None),
        )
    )
    if invoice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Invoice {invoice_id} not found. It may have been deleted; "
                "refresh the invoice list."
            ),
        )
    return invoice


_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$")


def _media_type(raw: str | None) -> str | None:
    """The bare ``type/subtype`` of a part's Content-Type, or ``None``.

    The header is the client's to write. Stored as sent, a perfectly ordinary
    ``application/pdf; name="..."`` — or anything longer than the 100
    characters ``invoices.content_type`` holds — overflowed the column on
    Postgres and the upload answered 500 (SQLite does not enforce the length,
    so the suite never saw it). Parameters also kept a real PDF out of
    ``ALLOWED_CONTENT_TYPES``, leaving the extension to vouch for it.
    """
    if not raw:
        return None
    media = raw.split(";", 1)[0].strip().lower()
    fits = len(media) <= Invoice.__table__.c.content_type.type.length
    return media if fits and _MEDIA_TYPE.match(media) else None


# What the first bytes of each binary format are. A file that claims one of
# these by its extension or its content type has to be one: the type check
# below passes on either claim, and before this nothing looked at the bytes —
# a Windows executable sent as application/pdf, a random blob named .xlsx or a
# truncated header named .png were stored and "parsed" into an invoice with no
# number, no date and a ₹0 total, counted against the monthly allowance, and
# (with a vision model configured) sent to it as a picture. Text formats need
# no signature. .xls is left out on purpose: what accounting software exports
# under that name is as often an HTML table or tab-separated text as it is an
# Excel 97 workbook, and the reader copes with all three.
_SIGNATURES: dict[str, tuple[str, ...]] = {
    "PDF": (".pdf",),
    "JPEG": (".jpg", ".jpeg"),
    "PNG": (".png",),
    "WebP": (".webp",),
    "HEIC": (".heic",),
    "Excel (.xlsx)": (".xlsx", ".xlsm"),
}
_KIND_OF_TYPE = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WebP",
    "image/heic": "HEIC",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
}


def _looks_like(kind: str, content: bytes) -> bool:
    if kind == "PDF":
        # The header may follow a little junk; readers look in the first 1 KB.
        return b"%PDF-" in content[:1024]
    if kind == "JPEG":
        return content.startswith(b"\xff\xd8\xff")
    if kind == "PNG":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if kind == "WebP":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if kind == "HEIC":
        return content[4:8] == b"ftyp"
    return content.startswith(b"PK\x03\x04")  # .xlsx and .xlsm are zip files


def _claimed_kinds(filename: str, content_type: str | None) -> set[str]:
    lowered = filename.lower()
    kinds = {kind for kind, exts in _SIGNATURES.items() if lowered.endswith(exts)}
    if content_type in _KIND_OF_TYPE:
        kinds.add(_KIND_OF_TYPE[content_type])
    return kinds


def _check_file_shape(filename: str, content_type: str | None, content: bytes) -> None:
    """The three checks every upload has to pass before it touches the database.

    Shared between the single and bulk endpoints so a file that would be
    refused alone is refused identically inside a batch, rather than the two
    paths drifting apart on which error a bad file gets.

    Each refusal names the file and says what to do about it. The app checks
    the same three things before it uploads anything (``fileError`` in
    ``lib/validate.js``), so a caller only reaches these when the two disagree
    — an operator who lowered ``MAX_UPLOAD_MB`` below the app's copy of it, a
    format the browser typed differently, a script posting straight at the API.
    Those are exactly the cases where "unsupported" on its own leaves someone
    with nothing to try.
    """
    lowered = filename.lower()
    if content_type not in ALLOWED_CONTENT_TYPES and not lowered.endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"{filename} cannot be read as an invoice "
                f"({content_type or 'no content type'}). Accepted: {ACCEPTED_LABEL}."
            ),
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            # Almost always a half-finished download or a cloud-sync
            # placeholder rather than a file anyone meant to send.
            detail=f"{filename} is empty (0 bytes). It may still be downloading.",
        )
    # Bytes, but nothing in them: a text export of spaces and newlines, or a
    # placeholder padded with NULs. No PDF or image is ever only this, so the
    # check costs real documents nothing. Let through, it was "parsed" into a
    # row of zeros with no number and no date — an invoice nobody can find
    # again, counted on the dashboard as one.
    if not content.lstrip(b"\xef\xbb\xbf").strip(b" \t\r\n\x0b\x0c\x00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{filename} has no text in it, only blank space. Export the "
                "invoice again, or upload the PDF or photo of it instead."
            ),
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            # Literal rather than the constant: Starlette renamed this to
            # HTTP_413_CONTENT_TOO_LARGE and deprecated the old spelling, so
            # either name ties us to a version range. The number does not move.
            status_code=413,
            # By how much, because that decides what to do: a phone scan a
            # little over is re-exported at a lower resolution, and one at
            # several times the limit is a batch that wants splitting.
            detail=(
                f"{filename} is {len(content) / (1024 * 1024):.1f} MB, over the "
                f"{settings.max_upload_mb} MB limit. Re-export it at a lower "
                "resolution or split it."
            ),
        )
    claimed = _claimed_kinds(filename, content_type)
    if claimed and not any(_looks_like(kind, content) for kind in claimed):
        names = " or ".join(sorted(claimed))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"{filename} is named or sent as {names}, but its contents are not "
                f"{'one' if len(claimed) == 1 else 'any of them'}. It may be damaged "
                "or only partly downloaded; open it to check, then export it again."
            ),
        )


def _store_and_extract(
    db: Session,
    tenant: invoice_service.TenantSnapshot,
    *,
    content: bytes,
    filename: str,
    content_type: str | None,
    invoice_type: InvoiceType,
    try_queue: bool = True,
    parse_inline: bool = True,
) -> tuple[Invoice, bool]:
    """Commit an upload and extract it, exactly as ``upload_invoice`` always has.

    ``try_queue`` and ``parse_inline`` exist for the bulk route's broker
    outage, and are left alone by everything else: see ``_BULK_INLINE_SECONDS``.

    Raises :class:`HTTPException` for a plan limit or a duplicate — the two
    ways storing the file itself can fail — so both callers report them the
    same way: as the request's own failure when there is only one file, and as
    one line in a batch when there are many.

    Takes the tenant as a snapshot rather than as the ``Business`` row, and
    that is not ceremony: this function commits, a commit expires every
    instance in the session, and so any attribute read off that row here would
    be a fresh ``SELECT`` on the second file of a batch and on every file after
    it. Read once by the caller, outside its loop.
    """
    try:
        invoice = invoice_service.create_pending_invoice(
            db,
            tenant,
            content=content,
            filename=filename,
            content_type=content_type,
            invoice_type=invoice_type,
            source=InvoiceSource.UPLOAD,
        )
    except invoice_service.PlanLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except invoice_service.DuplicateInvoice as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "invoice_id": exc.invoice_id},
        ) from exc
    except invoice_service.UploadNotStored as exc:
        # A 503 the caller can retry, not the generic 500: the file was refused
        # by storage, nothing of it was kept, and sending it again later is
        # exactly the right move.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{filename} could not be stored right now. Nothing was saved for "
                "it; try again in a few minutes."
            ),
            headers={"Retry-After": "120"},
        ) from exc

    queued = False
    if settings.celery_enabled and try_queue:
        from app.tasks.invoice_tasks import parse_invoice_task

        try:
            parse_invoice_task.delay(invoice.id)
            queued = True
        except Exception as exc:  # noqa: BLE001 - a dead broker must not lose the file
            # The row is already committed, so falling back to inline parsing
            # costs latency rather than the upload.
            logger.warning(
                "Could not queue invoice %s, parsing inline: %s",
                invoice.id, exc,
                extra={"invoice_id": invoice.id, "business_id": tenant.id},
            )

    if not queued and parse_inline:
        invoice = invoice_service.process_invoice(db, invoice, business_gstin=tenant.gstin)

    return invoice, queued


@router.post(
    "/upload",
    response_model=InvoiceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one invoice and extract its fields",
    description=(
        "Accepts a PDF, a photograph, a scan, or a CSV/Excel purchase register "
        "row. A PDF is read as text first and only falls back to the vision "
        "model when a page carries no extractable text — a scan.\n\n"
        "The file is stored and committed *before* it is parsed, so a "
        "rate-limited model costs a retry rather than the document. When "
        "`CELERY_ENABLED` is on the parse is queued and the response comes back "
        "with `queued: true` and an invoice still in `uploaded` status; poll "
        "`GET /invoices/{id}` for the result. With no reachable broker it "
        "parses inline instead, which is slower but never loses the upload.\n\n"
        "Duplicates are rejected two ways: the identical file (same SHA-256), "
        "or the same invoice number from the same counterparty. Claiming ITC "
        "twice on one invoice is what triggers a departmental notice."
    ),
    responses={
        201: {"description": "Stored. Parsed inline, or queued for a worker."},
        400: {"description": "The uploaded file is empty."},
        402: {"description": "The plan's monthly invoice allowance is used up."},
        409: {
            "description": (
                "Already on file. The body's `detail.invoice_id` points at the "
                "existing invoice."
            )
        },
        413: {"description": "Larger than `MAX_UPLOAD_MB`."},
        415: {"description": "Not a file type this product can read."},
    },
    dependencies=[Depends(_upload_limit), Depends(require_writer)],
)
async def upload_invoice(
    file: UploadFile = File(..., description="Invoice as PDF, image, CSV or Excel"),
    invoice_type: InvoiceType = Form(
        InvoiceType.PURCHASE,
        description="`purchase` (claims ITC) or `sales` (feeds GSTR-1).",
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceUploadResponse:
    """Upload one invoice and extract its fields.

    The file is stored and committed first, then parsed — either on a Celery
    worker or, when ``CELERY_ENABLED`` is off, inline. Parsing is the slow and
    failure-prone half (a free-tier model call), and separating it means a
    rate-limited model costs a retry rather than the document.
    """
    # The name reaches a filesystem path, a Content-Disposition header and the
    # UI, so it is reduced to something safe before any of that.
    filename = safe_filename(file.filename, fallback="invoice")
    content_type = _media_type(file.content_type)
    content = await file.read()
    _check_file_shape(filename, content_type, content)

    # Off the event loop. These handlers are ``async`` only to await the file
    # read; everything after it is blocking — the database, the file write,
    # and, whenever the broker is unreachable, the whole extraction inline: a
    # synchronous model call with a ninety-second timeout and its retries.
    # Called directly, that ran on the loop thread itself, so one upload during
    # a Redis outage froze every request this worker was serving, for every
    # tenant, for as long as the model took — and a fifty-file batch for
    # minutes. FastAPI already runs a plain ``def`` route in its threadpool;
    # this is the same, for the part that needs it.
    invoice, queued = await run_in_threadpool(
        _store_and_extract,
        db,
        invoice_service.TenantSnapshot.of(business),
        content=content,
        filename=filename,
        content_type=content_type,
        invoice_type=invoice_type,
    )

    return InvoiceUploadResponse(
        invoice=InvoiceDetailOut.from_invoice(invoice),
        queued=queued,
        message="Invoice queued for extraction" if queued else "Invoice processed",
    )


# A bulk request is a person dragging a folder in, not a script — bounded well
# below what abuse would need and well above what a month's paperwork is.
MAX_BULK_FILES = 50

# How long one batch may spend parsing inline once the broker is unreachable.
# The single-file fallback is right for one file and wrong for fifty: each paid
# the broker's connect timeout and a publish retry, then a model call of up to
# ``openrouter_call_budget_seconds`` — over an hour for a full batch, long after
# the proxy and the browser had given up on a request whose files were in fact
# being stored. After the first failed enqueue the rest of the batch stops
# asking the broker, and once this budget is spent files are stored
# ``uploaded``; the stalled-parse sweep queues them when the broker is back.
_BULK_INLINE_SECONDS = 60.0


@router.post(
    "/bulk",
    response_model=InvoiceBulkUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a batch of invoices in one request",
    description=(
        "The same checks and the same extraction path as `POST /invoices/upload`, "
        "run once per file — an unreadable type, an empty file, a duplicate or a "
        "plan limit rejects that file alone rather than the whole batch, so one "
        "bad page in a folder of fifty does not cost the other forty-nine.\n\n"
        f"Capped at {MAX_BULK_FILES} files per request, which the whole request "
        "is refused for exceeding — past that point the honest answer is several "
        "requests, not a batch a browser tab has to hold open until the last file "
        "is parsed.\n\n"
        "Once the plan's monthly allowance is used up, every file after that "
        "point in the batch is rejected the same way — files earlier in the "
        "batch that already fit under the limit are kept."
    ),
    responses={
        200: {"description": "Every file was attempted; check each item's `accepted`."},
        413: {"description": "More than the per-file or per-batch limit."},
    },
    dependencies=[Depends(_upload_limit), Depends(require_writer)],
)
async def upload_invoices_bulk(
    files: list[UploadFile] = File(..., description="One or more invoices"),
    invoice_type: InvoiceType = Form(
        InvoiceType.PURCHASE,
        description="Applied to every file in the batch.",
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceBulkUploadResponse:
    """Upload several invoices in one request, each validated and reported on its own."""
    if len(files) > MAX_BULK_FILES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"A batch is limited to {MAX_BULK_FILES} files; this one has "
                f"{len(files)}. Upload them in batches of {MAX_BULK_FILES} or fewer."
            ),
        )

    # Read once, before the loop, and held as plain data. Every file in the
    # batch commits, and each commit expires ``business`` — so *any* attribute
    # read off it inside the loop would be a ``SELECT`` per file for values
    # that cannot change between them. Expiry is per instance rather than per
    # column, which is why this is a snapshot of all three facts the loop needs
    # and not just the GSTIN: leaving one behind would have left the read.
    tenant = invoice_service.TenantSnapshot.of(business)

    items: list[InvoiceBulkUploadItemOut] = []
    broker_down = False
    inline_until = time.monotonic() + _BULK_INLINE_SECONDS
    for upload in files:
        filename = safe_filename(upload.filename, fallback="invoice")
        content_type = _media_type(upload.content_type)
        try:
            content = await upload.read()
            _check_file_shape(filename, content_type, content)
            # Off the loop for the reason ``upload_invoice`` gives.
            invoice, queued = await run_in_threadpool(
                _store_and_extract,
                db,
                tenant,
                content=content,
                filename=filename,
                content_type=content_type,
                invoice_type=invoice_type,
                try_queue=not broker_down,
                parse_inline=not settings.celery_enabled or time.monotonic() < inline_until,
            )
            if settings.celery_enabled and not queued:
                broker_down = True
        except HTTPException as exc:
            detail = exc.detail
            duplicate_id = None
            if isinstance(detail, dict):
                message = str(detail.get("message", ""))
                duplicate_id = detail.get("invoice_id")
            else:
                message = str(detail)
            items.append(
                InvoiceBulkUploadItemOut(
                    filename=filename,
                    accepted=False,
                    error=message,
                    duplicate_of_invoice_id=duplicate_id,
                )
            )
            continue
        except Exception:  # noqa: BLE001 - one file's failure is that file's line
            # A full volume, a dropped connection, a pool that ran dry. Raised,
            # these ended the whole request with the files before this one
            # already committed: the caller got a 500 and no per-file report,
            # and the obvious retry of the folder then answered "already
            # uploaded" for every file that had in fact gone through. The row
            # for this file was rolled back and its bytes discarded inside
            # ``create_pending_invoice``, so the honest line is "not stored,
            # send it again" — and the next file still gets its attempt.
            db.rollback()
            logger.exception(
                "Bulk upload could not store a file",
                extra={"business_id": tenant.id, "upload_filename": filename},
            )
            items.append(
                InvoiceBulkUploadItemOut(
                    filename=filename,
                    accepted=False,
                    error=(
                        "This file could not be stored because of a problem on our "
                        "side. Nothing was saved for it; upload it again."
                    ),
                )
            )
            continue

        items.append(
            InvoiceBulkUploadItemOut(
                filename=filename,
                accepted=True,
                invoice=InvoiceDetailOut.from_invoice(invoice),
                queued=queued,
            )
        )

    accepted = sum(1 for item in items if item.accepted)
    return InvoiceBulkUploadResponse(
        total=len(items), accepted=accepted, rejected=len(items) - accepted, items=items
    )


@router.get(
    "",
    response_model=InvoiceListOut,
    summary="List invoices, newest first",
    description=(
        "Paginated and filterable. Every filter is combined with AND, and the "
        "tenant scope is not optional — there is no parameter that widens it.\n\n"
        "`search` matches the invoice number or the counterparty name, "
        "case-insensitively. `%` and `_` in the term are matched literally "
        "rather than as wildcards: a bare `%` would otherwise turn an indexed "
        "lookup into a scan of the whole register."
    ),
    dependencies=[Depends(_read_limit)],
)
def list_invoices(
    invoice_type: InvoiceType | None = Query(
        default=None, description="Restrict to `sales` or `purchase`."
    ),
    invoice_status: InvoiceStatus | None = Query(
        default=None,
        alias="status",
        description="Extraction/reconciliation state, e.g. `parsed`, `mismatched`.",
    ),
    period: str | None = Query(
        default=None,
        pattern=gst_calendar.PERIOD_PATTERN,
        description="Filing period as `YYYY-MM`, derived from the invoice date.",
        examples=["2026-04"],
    ),
    counterparty_gstin: str | None = Query(
        default=None,
        max_length=15,
        description="Exact GSTIN of the supplier or customer. Case-insensitive.",
    ),
    search: str | None = Query(
        default=None,
        max_length=100,
        description="Substring of the invoice number or the counterparty name.",
    ),
    sort: InvoiceSort | None = Query(
        default=None,
        description=(
            "Sort order. Omitted means newest uploaded first. `value_*` sorts "
            "by what the invoice is worth — the stored total where there is "
            "one, taxable value plus tax where there is not — matching the "
            "figure every screen displays. Invoices with no date, or no "
            "number, sort last under `date_*` and `number_*` regardless of "
            "direction."
        ),
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size, 1-200."),
    offset: Offset = 0,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceListOut:
    """List this tenant's invoices, newest first."""
    conditions = [Invoice.business_id == business.id, Invoice.deleted_at.is_(None)]
    if invoice_type:
        conditions.append(Invoice.invoice_type == invoice_type)
    if invoice_status:
        conditions.append(Invoice.status == invoice_status)
    if period:
        conditions.append(Invoice.period == period)
    if counterparty_gstin:
        conditions.append(Invoice.counterparty_gstin == counterparty_gstin.strip().upper())
    pattern = search_pattern(search)
    if pattern:
        conditions.append(
            Invoice.invoice_number.ilike(pattern, escape="\\")
            | Invoice.counterparty_name.ilike(pattern, escape="\\")
        )

    total = int(db.scalar(select(func.count(Invoice.id)).where(*conditions)) or 0)
    # The requested sort, then upload order as a tiebreak — two invoices dated
    # the same day would otherwise not have a fixed order between one page and
    # the next, and a row could appear on both pages of the same query or on
    # neither.
    order = (*_SORTS.get(sort, ()), Invoice.created_at.desc(), Invoice.id.desc())
    # The register prints figures; the document behind each row is the detail
    # screen's business, and a page of 200 scanned PDFs is megabytes of it.
    rows = db.scalars(
        select(Invoice)
        .options(*without_document())
        .where(*conditions)
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    ).all()
    return InvoiceListOut(
        items=[InvoiceOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetailOut,
    summary="One invoice, with its extraction and warnings",
    description=(
        "Includes what the extractor read, how confident it was, and the "
        "warnings a reviewer should look at before the invoice is filed.\n\n"
        "An id belonging to another tenant answers 404, not 403: a 403 would "
        "confirm the id exists, which is enough to probe a competitor's invoice "
        "volume."
    ),
    responses={404: {"description": "No such invoice in this tenant."}},
    dependencies=[Depends(_read_limit)],
)
def get_invoice(
    invoice_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceDetailOut:
    return InvoiceDetailOut.from_invoice(_owned_invoice(db, business, invoice_id))


@router.patch(
    "/{invoice_id}",
    response_model=InvoiceDetailOut,
    summary="Apply a reviewer's corrections",
    description=(
        "A partial update: only the fields present in the body are touched.\n\n"
        "Correcting an invoice promotes it out of `failed` — a human has now "
        "supplied what the extractor could not, so it belongs in the filing "
        "pool rather than the error queue — sets `parsed_with` to `manual`, and "
        "sets confidence to 1.0. Changing `invoice_date` re-derives the filing "
        "period, and setting a `counterparty_gstin` on a purchase links or "
        "creates the supplier.\n\n"
        "`paid_at` and `is_capital_good` are the exception: they are ledger "
        "facts, not readings off the document, so recording one does not mark "
        "the extraction reviewed. They are also the two inputs the ITC reversal "
        "rules turn on — Rule 37 reverses the credit on a purchase left unpaid "
        "180 days past its invoice date, and Rule 43 spreads a capital good's "
        "credit over sixty months — so this is where a reversal is prevented or "
        "brought about."
    ),
    responses={
        404: {"description": "No such invoice in this tenant."},
        409: {
            "description": (
                "The correction would leave two invoices sharing one "
                "counterparty's document number. The conflicting invoice's id "
                "is on the response."
            )
        },
        422: {
            "description": (
                "A payment date in the future, or a pair of dates leaving the "
                "invoice paid before it was issued — whichever of the two this "
                "request moves. Clear `paid_at` in the same call to correct a "
                "date past a payment that never happened."
            )
        },
    },
    dependencies=[Depends(_write_limit), Depends(require_writer)],
)
def update_invoice(
    invoice_id: RowId,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceDetailOut:
    """Apply a reviewer's corrections.

    A corrected invoice is promoted out of ``FAILED``: a human has now supplied
    the fields the extractor could not, so it belongs in the filing pool rather
    than in the error queue. ``parsed_with`` records that a person touched it.
    """
    invoice = _owned_invoice(db, business, invoice_id)
    changes = payload.model_dump(exclude_unset=True)

    # Rule 37 counts from the invoice date, so a payment before it is not a
    # payment — it is a mistyped year, and it would silently cancel a reversal
    # that is genuinely due. Checked here rather than in the schema because it
    # needs the invoice: either date being compared may itself be arriving in
    # this same request.
    #
    # Both are read as "what the row will hold once this PATCH lands", not "what
    # this PATCH sends". Comparing only the incoming payment date left the rule
    # enforced in one direction: moving the *invoice* forward past a payment
    # already on file produced exactly the state the check exists to refuse, and
    # did it silently. That is not a hypothetical edit — correcting a misread
    # year is the commonest reason anyone touches this field — and the invoice
    # it leaves behind reads as paid forever, so its credit never reverses under
    # Rule 37 however long the supplier goes unpaid.
    paid_at = changes.get("paid_at", invoice.paid_at)
    invoice_date = changes.get("invoice_date", invoice.invoice_date)
    if paid_at is not None and invoice_date is not None and paid_at < invoice_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Paid on {paid_at.isoformat()}, but the invoice is dated "
                f"{invoice_date.isoformat()}. An invoice cannot be paid before it "
                "was issued."
            ),
        )

    # A correction can walk this invoice onto another one's natural key —
    # retyping the document number, or fixing the counterparty GSTIN onto a
    # supplier who already has an invoice by that number. The database refuses
    # it either way, but the refusal arrived as an unhandled flush deep inside
    # ``get_or_create_supplier`` below, which left the session unusable and the
    # reviewer looking at a 500 and a correlation id. The upload path already
    # answers 409 and names the invoice in the way; a correction is the same
    # conflict and deserves the same answer, checked before anything is
    # written so a refused edit touches nothing.
    if "invoice_number" in changes or "counterparty_gstin" in changes:
        number = changes.get("invoice_number", invoice.invoice_number)
        counterparty = changes.get("counterparty_gstin", invoice.counterparty_gstin)
        clash = invoice_service.find_duplicate(
            db,
            business.id,
            invoice_type=invoice.invoice_type,
            counterparty_gstin=counterparty,
            invoice_number=number,
        )
        if clash is not None and clash.id != invoice.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"Invoice {number} from {counterparty} is already on file "
                        f"as invoice {clash.id}."
                    ),
                    "invoice_id": clash.id,
                },
            )

    for attr, value in changes.items():
        setattr(invoice, attr, value)

    if "invoice_date" in changes and invoice.invoice_date:
        invoice.period = invoice.invoice_date.strftime("%Y-%m")

    # Two kinds of edit arrive here and they must not be conflated. Correcting a
    # field means a human has read the document and overridden what the
    # extractor made of it, which is what ``manual`` and a confidence of 1.0
    # assert. Recording that a supplier was paid, or that a purchase was capital
    # goods, asserts nothing about the extraction at all — those facts are not
    # on the invoice to be read. Treating them as a correction marked the row
    # reviewed and took it off the needs-review list, so a document nobody had
    # looked at stopped being flagged for it; on a ``failed`` row it also
    # promoted the invoice into the filing pool, putting fields that were never
    # extracted into a return.
    # ``itc_eligible`` is the third: whether the credit is blocked under
    # s.17(5) is a decision about the purchase — the motor car, the staff
    # catering — and nothing on the document says so. Left out of this set,
    # marking a ``failed`` row's credit blocked promoted it exactly as a
    # payment used to.
    LEDGER_FIELDS = {"paid_at", "is_capital_good", "itc_eligible"}
    corrections = set(changes) - LEDGER_FIELDS

    if corrections:
        invoice.parsed_with = "manual"
        invoice.extraction_confidence = 1.0
        # Every status that means "the figures on this row were never
        # extracted" — which is what a correction has just stopped being true.
        #
        # This listed ``FAILED`` and ``UPLOADED`` and left ``PROCESSING`` out,
        # and ``PROCESSING`` is the one nothing else can rescue. A worker that
        # dies mid-parse leaves the row there permanently: the extraction is
        # never coming back to move it, and the row is in
        # ``UNREADABLE_STATUSES``, so filing, the credit pool and the tax
        # summary all skip it. Typing the figures in by hand — the obvious
        # thing to do about a document stuck on a spinner — answered 200,
        # recorded ``manual`` and a confidence of 1.0, and changed nothing:
        # the supply stayed out of GSTR-1 and out of the period's output tax,
        # while ``/filing/validate`` went on advising the user to wait for an
        # extraction to finish. Under-declared output tax carries interest, and
        # the product had told them it was in hand.
        #
        # The other direction too. ``matched`` is a reconciliation's verdict on
        # the figures it compared, and a correction to one of them — or to the
        # number and GSTIN the row was found by, or the date that decides
        # which period's run judges it — is a figure no run has seen. The row
        # kept the badge, so a list filtered by ``matched`` went on offering
        # the corrected invoice as credit the supplier had confirmed. Back to
        # ``parsed``: the next run over the period restores whichever verdict
        # the new figures earn, and nothing in between claims one. An HSN code
        # or a name is left alone, because the statement carries neither and
        # the run never read them.
        _DUPLICATE_IDENTITY = {"counterparty_gstin", "invoice_number"}
        if invoice.status == InvoiceStatus.DUPLICATE:
            withdrawn = bool(corrections & _DUPLICATE_IDENTITY)
        else:
            withdrawn = invoice.status in VERDICT_STATUSES and bool(corrections & RECONCILED_FIELDS)
        if invoice.status in UNREADABLE_STATUSES or withdrawn:
            invoice.status = InvoiceStatus.PARSED
    if changes and invoice.invoice_type == InvoiceType.PURCHASE and invoice.counterparty_gstin:
        supplier = invoice_service.get_or_create_supplier(
            db, business.id, invoice.counterparty_gstin, invoice.counterparty_name
        )
        invoice.supplier_id = supplier.id
    elif "counterparty_gstin" in changes and not invoice.counterparty_gstin:
        # A GSTIN cleared — usually because the extractor misread it — left
        # the row linked to the supplier it named, so the invoice stayed
        # attributed to a supplier it no longer says it came from.
        invoice.supplier_id = None

    db.commit()
    db.refresh(invoice)
    # The audit line for an edit. The access line beside it (same correlation
    # id) says who and which invoice; this says what was touched, which is the
    # question an assessment asks of a corrected taxable value or tax amount.
    # Field names, not values: the figures are in the database, and the log
    # is the lower-trust store.
    logger.info(
        "Invoice edited",
        extra={
            "business_id": business.id,
            "invoice_id": invoice.id,
            "corrected_fields": sorted(corrections),
            "ledger_fields": sorted(set(changes) & LEDGER_FIELDS),
        },
    )
    return InvoiceDetailOut.from_invoice(invoice)


@router.post(
    "/{invoice_id}/reparse",
    response_model=InvoiceDetailOut,
    summary="Re-run extraction over the stored file",
    description=(
        "Useful after a parser improvement, or when a model was rate-limited "
        "and the heuristic fallback did a poor job. The original file is kept "
        "precisely so this does not require re-photographing anything.\n\n"
        "Always runs inline — the caller is waiting on the answer — so it is "
        "limited more tightly than upload."
    ),
    responses={
        404: {"description": "No such invoice in this tenant."},
        409: {"description": "The invoice is a duplicate or currently being processed."},
    },
    dependencies=[Depends(_reparse_limit), Depends(require_writer)],
)
def reparse_invoice(
    invoice_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> InvoiceDetailOut:
    """Re-run extraction over the stored file.

    Always inline: the caller asked for this and is waiting on the answer,
    unlike an upload where the queue is what keeps the request fast.
    """
    invoice = _owned_invoice(db, business, invoice_id)
    if invoice.status == InvoiceStatus.DUPLICATE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This invoice is a duplicate — re-reading the file cannot "
                "change that. Correct the invoice number or counterparty "
                "GSTIN, or delete one of the two copies."
            ),
        )
    # The check above is a read, and this is the claim. ``process_invoice``
    # writes ``processing`` unconditionally, so two reparses of one row — a
    # double-click, or the owner and their CA at once — both passed the check
    # and both ran the model over the same file, and a reparse of a row still
    # ``uploaded`` raced the queued auto-parse the same way. Only the request
    # that moves the row out of the status it was read in goes on to parse
    # it; the task's own claim then sees ``processing`` and stands down.
    claimed = invoice.status != InvoiceStatus.PROCESSING and db.execute(
        update(Invoice)
        .where(
            Invoice.id == invoice.id,
            Invoice.business_id == business.id,
            Invoice.status == invoice.status,
            Invoice.deleted_at.is_(None),
        )
        .values(status=InvoiceStatus.PROCESSING)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    if not claimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This invoice is currently being processed. Wait for the "
                "extraction to finish before requesting a reparse."
            ),
        )
    # One invoice, so this is not the loop the parameter exists for — but the
    # tenant is already loaded and in hand, and taking it here keeps the
    # relationship walk to the one caller that genuinely has nothing else.
    return InvoiceDetailOut.from_invoice(
        invoice_service.process_invoice(db, invoice, business_gstin=business.gstin)
    )


@router.delete(
    "/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # `from __future__ import annotations` turns the `-> None` below into the
    # NoneType *class*, which FastAPI reads as a real response model and then
    # rejects for a 204. Saying "no model" explicitly keeps the annotation honest.
    response_model=None,
    summary="Remove an invoice from the books",
    description=(
        "A soft delete: `deleted_at` is set, and the row and the stored file "
        "both stay. A GST filing can be reopened years later during an "
        "assessment, and a row that is gone cannot be explained to an officer."
    ),
    responses={
        204: {"description": "Deleted."},
        404: {"description": "No such invoice in this tenant."},
    },
    dependencies=[Depends(_write_limit), Depends(require_writer)],
)
def delete_invoice(
    invoice_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> None:
    """Soft-delete an invoice. The row and the stored file both stay."""
    invoice = _owned_invoice(db, business, invoice_id)
    invoice.soft_delete()
    db.commit()
    # The edit route leaves an audit line; removing an invoice from the books
    # is the larger change and left none. Period and type say which return it
    # just left.
    logger.info(
        "Invoice deleted",
        extra={
            "business_id": business.id,
            "invoice_id": invoice.id,
            "invoice_type": invoice.invoice_type.value,
            "period": invoice.period,
            "status": invoice.status.value,
        },
    )
