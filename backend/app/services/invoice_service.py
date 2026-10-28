"""Persisting invoices: storage, plan limits, dedup, and the parse write-back.

The router stays thin and this module owns the rules, because the same three
steps have to happen identically whether an invoice arrives from the upload
endpoint, an inbound email, or a WhatsApp photo.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import and_, case, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.core.config import settings
from app.core.sanitize import clean_text, safe_extension, strip_control_chars, without_nul
from app.models.business import Business
from app.models.invoice import (
    UNCOUNTABLE_STATUSES,
    Invoice,
    InvoiceSource,
    InvoiceStatus,
    InvoiceType,
)
from app.models.subscription import Subscription, SubscriptionTier
from app.models.supplier import Supplier
from app.services import gst_calendar, jev_service
from app.services import gstin as gstin_service
from app.services.invoice_parser import ParsedInvoice, parse_invoice

logger = logging.getLogger(__name__)


class PlanLimitExceeded(RuntimeError):
    """The tenant has used up their plan's invoices for the month."""


class DuplicateInvoice(RuntimeError):
    """This exact file, or this invoice number, is already on file."""

    def __init__(self, message: str, invoice_id: int) -> None:
        super().__init__(message)
        self.invoice_id = invoice_id


def month_of(moment: datetime | None = None) -> str:
    """The current filing period as ``YYYY-MM``, in India.

    This is the period the dashboard, the ITC screen and the filing endpoints
    fall back to when the caller names none, so it is a question about the
    Indian calendar and not about the server's. A box on UTC still reads last
    month until 05:30 IST on the 1st, which would open the new month's
    dashboard on the month that has just closed.

    An explicit *moment* is converted rather than read as-is, so a caller that
    passes a UTC instant gets the Indian date it fell on.
    """
    return gst_calendar.period_of(
        gst_calendar.ist_date(moment) if moment else gst_calendar.today_ist()
    )


def month_bounds(period: str) -> tuple[datetime, datetime]:
    """The instants a ``YYYY-MM`` period begins and ends, as UTC.

    The boundary is midnight *in India* — that is when a business's month rolls
    over and when their plan's allowance should reset — but it is returned in
    UTC because that is what the stored timestamps are.

    Converting rather than handing an IST-aware value straight to the query is
    load-bearing. On Postgres a ``timestamptz`` comparison normalises either
    one correctly; SQLAlchemy's SQLite type formats whatever wall clock the
    value carries and drops the offset, so an IST-aware bound would compare
    ``00:00`` against UTC-stored rows and be five and a half hours out — right
    in production, wrong in the suite, which is the split nothing catches.
    """
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1, tzinfo=gst_calendar.IST)
    end = (
        datetime(year + 1, 1, 1, tzinfo=gst_calendar.IST)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=gst_calendar.IST)
    )
    return start.astimezone(UTC), end.astimezone(UTC)


def monthly_usage(db: Session, business_id: int, period: str | None = None) -> int:
    """Invoices uploaded by this tenant in *period* (default: this month).

    Counts by upload month rather than by invoice date, because the plan sells
    processing capacity — a business catching up on last quarter's paperwork is
    using this month's capacity to do it.

    The month is the Indian one. Counted against UTC midnight instead, a
    business that used up October's allowance stays blocked until 05:30 IST on
    1 November — they are told to upgrade on a day their plan has already
    reset — and the invoices they upload in those hours are charged to the
    month that closed.
    """
    period = period or month_of()
    start, end = month_bounds(period)
    return int(
        db.scalar(
            select(func.count(Invoice.id)).where(
                Invoice.business_id == business_id,
                Invoice.deleted_at.is_(None),
                Invoice.created_at >= start,
                Invoice.created_at < end,
            )
        )
        or 0
    )


# The invoice allowance a paid subscription buys, by tier. The cap is keyed
# by `business.plan`, and buying a plan never wrote that column — so a
# business that paid for Pro stayed capped at the free plan's fifty invoices
# and, at fifty, was told to "upgrade to continue uploading".
_TIER_PLAN = {SubscriptionTier.PRO: "pro", SubscriptionTier.ENTERPRISE: "ca_bundle"}


def effective_plan(business: Business) -> str:
    """The plan whose limits apply: a paid, unlapsed subscription's, else the business's own.

    Read through the business's own session, so every caller that already has
    the business gets the same answer as `require_paid_tier` without a new
    argument. A lapsed period falls back to the stored plan, as the paywall does.
    """
    db = object_session(business)
    if db is not None:
        sub = db.scalar(select(Subscription).where(Subscription.business_id == business.id))
        if sub is not None and sub.is_paid():
            return _TIER_PLAN.get(sub.tier, business.plan.value)
    return business.plan.value


def plan_limit(business: Business) -> int:
    """Monthly invoice cap for this tenant's plan; 0 means unlimited."""
    return settings.plan_limits.get(effective_plan(business), 0)


@dataclass(frozen=True)
class TenantSnapshot:
    """The tenant facts an upload needs, lifted out of the session.

    Storing an invoice commits, and a commit expires every instance in the
    session — so a ``Business`` attribute read inside a batch loop is a fresh
    ``SELECT`` on ``businesses`` for a value that cannot change between files.

    The trap is that it does not matter *which* attribute. Expiry is per
    instance, not per column: the first access after a commit reloads the whole
    row, so removing the plan lookup on its own would have moved the read onto
    ``business.id`` two lines below and changed nothing a query counter could
    see. The only fix that holds is not touching the instance in the loop at
    all, which is what this exists to make possible — read once, before the
    first file, as plain data no commit can expire.

    Frozen for the same reason: a snapshot that could be written to would
    invite code that "updates" it and silently diverges from the row.
    """

    id: int
    gstin: str | None
    plan: str
    monthly_limit: int

    @classmethod
    def of(cls, business: Business) -> TenantSnapshot:
        """Take the snapshot. Call once per request, outside any loop."""
        return cls(
            id=business.id,
            gstin=business.gstin,
            plan=effective_plan(business),
            monthly_limit=plan_limit(business),
        )


def check_plan_limit(db: Session, tenant: TenantSnapshot) -> None:
    """Raise :class:`PlanLimitExceeded` if the tenant is at their cap.

    The cap comes off the snapshot and the usage is counted fresh, which is
    what makes a batch stop at the right file rather than at the first or not
    at all: the plan cannot change mid-request, and the count rises with every
    file the batch has already stored.
    """
    if tenant.monthly_limit and monthly_usage(db, tenant.id) >= tenant.monthly_limit:
        raise PlanLimitExceeded(
            f"Plan '{tenant.plan}' allows {tenant.monthly_limit} invoices per month. "
            "Upgrade to continue uploading."
        )


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_upload(content: bytes, filename: str, business_id: int) -> str:
    """Write the upload to disk and return its path.

    Namespaced by tenant and prefixed with a UUID: two businesses both
    uploading "invoice.pdf" must not be able to reach each other's file, and
    the stored name must not be attacker-controlled.
    """
    directory = Path(settings.upload_dir) / str(business_id)
    directory.mkdir(parents=True, exist_ok=True)
    # Only a plain alphanumeric extension survives. This took the client's
    # suffix as-is, so "shell.php;jpg" was stored as "<uuid>.php;jpg";
    # `safe_extension` was written for exactly this and never called.
    suffix = safe_extension(filename)
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    return str(path)


def _discard_upload(path: str | None) -> None:
    """Remove a stored file whose row was never committed.

    Best effort, and deliberately silent about failure: this runs while an
    exception is already on its way up, and the caller is entitled to see that
    one rather than an unlink error raised on top of it. A file left behind
    because the volume went read-only is the same orphan as before, which is
    the state this is trying to improve on rather than guarantee.
    """
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001 - the original failure is the story
        logger.warning("Could not remove the orphaned upload %s: %s", path, exc)


def find_duplicate(
    db: Session,
    business_id: int,
    *,
    digest: str | None = None,
    invoice_type: InvoiceType | None = None,
    counterparty_gstin: str | None = None,
    invoice_number: str | None = None,
) -> Invoice | None:
    """An existing invoice that this upload would duplicate, if any.

    Two ways to be a duplicate, checked in this order: the identical file
    (same SHA-256), or the same invoice number from the same counterparty.
    """
    if digest:
        existing = db.scalar(
            select(Invoice).where(
                Invoice.business_id == business_id,
                Invoice.file_hash == digest,
                Invoice.deleted_at.is_(None),
            )
        )
        if existing:
            return existing
    if invoice_type and counterparty_gstin and invoice_number:
        return db.scalar(
            select(Invoice).where(
                Invoice.business_id == business_id,
                Invoice.invoice_type == invoice_type,
                Invoice.counterparty_gstin == counterparty_gstin,
                Invoice.invoice_number == invoice_number,
                Invoice.deleted_at.is_(None),
            )
        )
    return None


def _find_supplier(db: Session, business_id: int, gstin: str) -> Supplier | None:
    """The live supplier row for *gstin*, without writing anything to get it.

    Autoflush is off for the same reason the caller flushes one row at a time:
    a plain query writes out everything the session has pending first, so a
    caller part-way through an edit of its own had that edit hit the database
    from inside a *lookup*. The supplier this reads is always already committed
    or already flushed by the insert below, so there is nothing pending this
    query needs to see.
    """
    with db.no_autoflush:
        return db.scalar(
            select(Supplier).where(
                Supplier.business_id == business_id,
                Supplier.gstin == gstin,
                Supplier.deleted_at.is_(None),
            )
        )


def _insert_supplier(db: Session, business_id: int, gstin: str, name: str | None) -> None:
    """INSERT one supplier row inside a SAVEPOINT of its own.

    Deliberately a Core INSERT on a connection-level SAVEPOINT rather than
    ``Session.begin_nested()`` around ``Session.add``. Releasing an *ORM*
    nested transaction flushes the whole session on the way out, so a caller
    part-way through an edit of its own — the invoice PATCH route sets its
    fields and then reaches this function to link the supplier — had that edit
    written from inside this SAVEPOINT. When the caller's change was the one
    the database refused, the handler below read a conflict that had nothing to
    do with any supplier as a lost race, re-queried a session whose transaction
    was already dead, and turned what should have been a 409 about the invoice
    into a ``PendingRollbackError`` and a 500.

    Narrowing the ORM flush was not enough: the flush that broke it came from
    releasing the savepoint, not from the ``add``. Going through the connection
    keeps the SAVEPOINT holding what it claims to hold — one INSERT, whose
    failure means exactly one thing — and leaves the caller's pending edits
    where they belong, unwritten and the caller's to commit or discard.
    """
    connection = db.connection()
    savepoint = connection.begin_nested()
    try:
        connection.execute(
            insert(Supplier).values(
                business_id=business_id,
                gstin=gstin,
                legal_name=name,
                state_code=gstin_service.state_code_of(gstin),
            )
        )
    except IntegrityError:
        savepoint.rollback()
        raise
    savepoint.commit()


def get_or_create_supplier(
    db: Session, business_id: int, gstin: str, name: str | None = None
) -> Supplier:
    """The supplier row for *gstin* under this tenant, creating it if new.

    Look-then-insert has a window in it, and this is the one place in the
    product that runs concurrently on the same key: a business uploading a
    folder of invoices from a supplier they have never bought from before has
    several workers reaching this line at once, each having looked and found
    nothing. One of them inserts; the rest hit ``uq_suppliers_business_gstin``.

    That is a lost race, not a failure, and it was being reported as neither.
    The insert happens inside the caller's transaction, so the integrity error
    surfaced up in :func:`process_invoice` — whose handler exists for the
    *invoice's* natural key and assumes any conflict is one. A perfectly good
    invoice was therefore marked ``failed`` and told the user "This invoice is
    already on file", which was false, named a document that does not exist, and
    dropped the invoice out of the filing pool over a row the other worker had
    already created correctly.

    The insert is wrapped in a SAVEPOINT so a conflict rolls back that statement
    alone and leaves the session usable, and the winner's row is then read back.
    Whoever inserts, both callers end up with the same supplier.

    Neither the lookup nor the insert writes anything else the session happens
    to have pending; see :func:`_find_supplier` and :func:`_insert_supplier` for
    why that matters to callers who are part-way through an edit of their own.
    """
    supplier = _find_supplier(db, business_id, gstin)
    if supplier is None:
        try:
            _insert_supplier(db, business_id, gstin, name)
        except IntegrityError:
            # Somebody else got there first. Their row is the one that exists.
            supplier = _find_supplier(db, business_id, gstin)
            if supplier is None:
                # The conflict was not the one this handles — a soft-deleted row
                # holding the GSTIN, say. Let it surface rather than pretending.
                raise
        else:
            # Read back rather than trusting the INSERT: the ORM object is what
            # callers hold, and this is the one place it enters the session.
            supplier = _find_supplier(db, business_id, gstin)
            if supplier is None:  # pragma: no cover - the row was just written
                raise RuntimeError(f"Supplier {gstin} vanished after insert")
    if name and not supplier.legal_name:
        supplier.legal_name = name
    return supplier


def create_pending_invoice(
    db: Session,
    tenant: TenantSnapshot,
    *,
    content: bytes,
    filename: str,
    content_type: str | None,
    invoice_type: InvoiceType,
    source: InvoiceSource = InvoiceSource.UPLOAD,
) -> Invoice:
    """Store an upload and record it as awaiting extraction.

    Committed before any parsing happens, so the file is durably ours the
    moment the request returns. Extraction can then run on a worker, fail, and
    be retried without the user needing the paper again.

    Takes a :class:`TenantSnapshot` rather than the ``Business`` row: this
    function commits, and a caller looping over a batch would pay a reload of
    that row on every file after the first. See the snapshot's own docstring.
    """
    check_plan_limit(db, tenant)

    digest = file_hash(content)
    duplicate = find_duplicate(db, tenant.id, digest=digest)
    if duplicate is not None:
        raise DuplicateInvoice(
            f"This file was already uploaded as invoice {duplicate.id}", duplicate.id
        )

    stored = store_upload(content, filename, tenant.id)
    invoice = Invoice(
        business_id=tenant.id,
        invoice_type=invoice_type,
        status=InvoiceStatus.UPLOADED,
        source=source,
        source_filename=filename,
        content_type=content_type,
        file_size=len(content),
        file_hash=digest,
        storage_path=stored,
    )
    db.add(invoice)
    try:
        db.commit()
    except Exception:
        # The bytes are on disk before the row that names them exists, and they
        # have to be: ``storage_path`` is a column on that row. So a commit
        # that fails leaves a file nothing in the database points at, and
        # nothing ever will — no query reads ``upload_dir``, the delete route
        # keeps stored files on purpose, and there is no sweeper. Every upload
        # that meets a full pool, a dropped connection or a constraint
        # therefore leaves a permanent orphan, on a volume sized for the rows
        # that exist rather than for the ones that failed to.
        #
        # Deleted here rather than swept later because this is the only moment
        # anything knows the path is unreferenced; after the rollback it is
        # indistinguishable from a file whose row was written by a request that
        # is still in flight.
        db.rollback()
        _discard_upload(stored)
        raise
    db.refresh(invoice)
    # One line per stored document. A bulk upload's access line names no
    # invoice — its path has no id — so without this nothing said which rows a
    # batch created, or by which route they arrived.
    logger.info(
        "Invoice stored",
        extra={
            "business_id": invoice.business_id,
            "invoice_id": invoice.id,
            "invoice_type": invoice.invoice_type.value,
            "source": invoice.source.value,
        },
    )
    return invoice


def apply_parsed(
    db: Session,
    invoice: Invoice,
    parsed: ParsedInvoice,
    *,
    business_gstin: str | None = None,
) -> Invoice:
    """Write an extraction onto an invoice row and link its counterparty.

    Which party is "the counterparty" flips with direction: on a purchase we
    are the buyer and the supplier is the other side, on a sale it is the
    reverse. Getting this backwards would file our own GSTIN as the vendor on
    every purchase, so it is decided here once rather than at each call site.

    *business_gstin* is the tenant's own GSTIN, and it is a parameter rather
    than a walk down ``invoice.business`` because of who calls this in a loop.
    That relationship is lazy, and :func:`process_invoice` commits immediately
    before reaching here — a commit expires every instance in the session, so
    the walk costs a fresh ``SELECT`` on ``businesses`` *every* time, not just
    the first. One per file through a fifty-file batch, for a value that is
    the same on all fifty. A caller holding the tenant passes it; the walk
    stays as the fallback for the one caller that does not.
    """
    if business_gstin is None:
        # The Celery path: the task has an invoice id and nothing else. One
        # invoice per task, so the read here is per task and not per file.
        business_gstin = invoice.business.gstin if invoice.business else None

    if invoice.invoice_type == InvoiceType.PURCHASE:
        counterparty = parsed.supplier_gstin
        counterparty_name = parsed.supplier_name
        # A supplier who filled in only one GSTIN put their own on the
        # invoice; if it happens to be ours, the other one is theirs.
        if counterparty and business_gstin and counterparty == business_gstin:
            counterparty = parsed.buyer_gstin
            counterparty_name = parsed.buyer_name
    else:
        counterparty = parsed.buyer_gstin
        counterparty_name = parsed.buyer_name
        if counterparty and business_gstin and counterparty == business_gstin:
            counterparty = parsed.supplier_gstin
            counterparty_name = parsed.supplier_name

    invoice.counterparty_gstin = counterparty
    # Cleaned as the registration form cleans a name, because these come out
    # of a document rather than a form: a PDF's text can carry NUL (which
    # PostgreSQL refuses, failing the whole save) and bidi overrides (which
    # make a name render as something other than what was approved).
    invoice.counterparty_name = clean_text(counterparty_name, max_length=255)
    invoice.invoice_number = (
        strip_control_chars(parsed.invoice_number).strip()[:64] or None
        if parsed.invoice_number
        else None
    )
    invoice.invoice_date = parsed.invoice_date
    invoice.period = parsed.period
    invoice.place_of_supply = parsed.place_of_supply
    invoice.hsn_code = parsed.hsn_code
    invoice.taxable_value = parsed.taxable_value
    invoice.cgst = parsed.cgst
    invoice.sgst = parsed.sgst
    invoice.igst = parsed.igst
    invoice.cess = parsed.cess
    invoice.total_value = parsed.total_value
    invoice.tax_rate = parsed.tax_rate
    invoice.reverse_charge = parsed.reverse_charge
    invoice.line_items = without_nul(parsed.line_items) or None
    invoice.raw_text = without_nul(parsed.raw_text) or None
    invoice.extraction = without_nul(parsed.as_dict())
    invoice.parsed_with = parsed.parsed_with
    invoice.extraction_confidence = parsed.confidence
    invoice.parse_error = None
    invoice.status = InvoiceStatus.PARSED

    # A purchase from an identifiable supplier gets a supplier row, which is
    # what the compliance score is later built on.
    if invoice.invoice_type == InvoiceType.PURCHASE and counterparty:
        supplier = get_or_create_supplier(db, invoice.business_id, counterparty, counterparty_name)
        invoice.supplier_id = supplier.id

    # Jev's supply category, compliance risk, tax route and (when the parser
    # found no code) HSN chapter. Stored beside the extraction for the review
    # screen and never over a field: the tax heads stay whatever the document
    # and the state codes say. Absent when Jev is off or unreachable.
    assessment = jev_service.assess_invoice(invoice, business_gstin=business_gstin)
    if assessment is not None:
        invoice.extraction = {**invoice.extraction, "jev": assessment}

    return invoice


def process_invoice(
    db: Session, invoice: Invoice, *, business_gstin: str | None = None
) -> Invoice:
    """Parse a stored invoice and record the outcome. Never raises.

    *business_gstin* is threaded straight through to :func:`apply_parsed`; see
    there for why a caller in a loop should pass it.

    A failure is written to the row as ``FAILED`` with the reason, rather than
    propagating: this runs on a Celery worker where an exception would be a
    log line nobody reads, and the user needs to see which of their fifty
    uploads needs attention.

    The write-back is inside the guarded block as well as the parse. Committing
    outside it is what leaves a row stuck in ``PROCESSING``: the parse can
    succeed and the *insert* still fail, and the user is then watching a
    spinner for a document nothing is coming back to.
    """
    invoice.status = InvoiceStatus.PROCESSING
    db.commit()

    # Captured as soon as they are known. A rollback reverts them on the
    # instance, and they are the only detail that makes the message below
    # worth reading.
    number: str | None = None
    counterparty: str | None = None
    started = time.perf_counter()
    # Read once, up front: a rollback below expires the instance, and the
    # tenant is the one field every line out of here has to carry — a log
    # searched by business is how "my April upload failed" gets answered.
    business_id = invoice.business_id

    try:
        path = Path(invoice.storage_path) if invoice.storage_path else None
        content = path.read_bytes() if path and path.exists() else None
        if content is None and not invoice.raw_text:
            raise FileNotFoundError(f"Stored file is missing: {invoice.storage_path}")

        parsed = parse_invoice(
            content=content,
            content_type=invoice.content_type,
            filename=invoice.source_filename,
            text=invoice.raw_text,
        )
        apply_parsed(db, invoice, parsed, business_gstin=business_gstin)
        number, counterparty = invoice.invoice_number, invoice.counterparty_gstin
        db.commit()
        # The success line. Until this existed a parse that worked left no
        # trace at all — the task's return value goes to a result backend
        # nobody reads — so the rate at which the model was falling back to
        # the heuristics, the one number that says whether the provider is
        # earning its keep, could only be had by querying ``parsed_with`` off
        # the rows. ``parsed_with`` names the path taken; ``duration_ms`` is
        # the whole parse, file read to commit.
        logger.info(
            "Invoice %s parsed", invoice.id,
            extra=_parse_outcome(invoice, business_id, started),
        )
    except IntegrityError:
        # The same invoice number from the same counterparty is already on
        # file. Only discoverable here: the number is not known until the
        # document has been read, so the dedup at upload time can compare
        # nothing but file hashes — and a re-scan of a paper invoice is a
        # different file every time.
        db.rollback()
        existing = find_duplicate(
            db,
            invoice.business_id,
            invoice_type=invoice.invoice_type,
            counterparty_gstin=counterparty,
            invoice_number=number,
        )
        invoice.status = InvoiceStatus.FAILED
        invoice.parse_error = _duplicate_message(number, existing)
        db.commit()
        logger.info(
            "Invoice %s duplicates invoice %s", invoice.id, existing.id if existing else "?",
            extra=_parse_outcome(invoice, business_id, started, duplicate_of=existing),
        )
    except Exception as exc:  # noqa: BLE001 - the row is the error channel
        # Rollback before writing the failure: a half-applied extraction is
        # worse than none, and after a failed flush the session refuses to
        # commit anything at all until it is cleared.
        db.rollback()
        invoice.status = InvoiceStatus.FAILED
        invoice.parse_error = str(exc)[:2000]
        db.commit()
        # Logged after the write-back, not before it: the outcome fields read
        # the row, and before the commit the row still says ``processing``.
        # ``exc_info`` is the exception that was in flight, so this is still
        # the traceback a plain ``logger.exception`` would have carried.
        logger.error(
            "Invoice %s failed to parse", invoice.id,
            exc_info=exc,
            extra=_parse_outcome(invoice, business_id, started),
        )

    db.refresh(invoice)
    return invoice


def _parse_outcome(
    invoice: Invoice,
    business_id: int,
    started: float,
    *,
    duplicate_of: Invoice | None = None,
) -> dict[str, object]:
    """The structured fields every line out of :func:`process_invoice` carries.

    One builder for all three outcomes so a dashboard can group by ``status``
    and ``parsed_with`` without caring which branch wrote the line. The
    tenant is passed in rather than read off the row because the failure
    branch has rolled back by the time it logs, and an expired instance
    would issue a query to answer for a field this function had all along.
    """
    fields: dict[str, object] = {
        "invoice_id": invoice.id,
        "business_id": business_id,
        "status": invoice.status.value,
        "parsed_with": invoice.parsed_with,
        "confidence": invoice.extraction_confidence,
        "content_type": invoice.content_type,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if duplicate_of is not None:
        fields["duplicate_of"] = duplicate_of.id
    return fields


def _duplicate_message(number: str | None, existing: Invoice | None) -> str:
    """Why the row failed, in the words of someone who uploaded a document.

    The constraint name and the psycopg traceback are true and useless; what
    the user needs is which invoice this repeats so they can delete one.
    """
    named = f"Invoice {number}" if number else "This invoice"
    if existing is not None:
        return f"{named} is already on file as invoice {existing.id}."
    return f"{named} is already on file."


# What the row says once the reaper has given up on it. Written to
# ``parse_error``, so it is the sentence the review screen shows beside the
# document, and phrased as the next action rather than as a diagnosis: the
# stored file is untouched and re-extraction is one button away.
STALLED_PARSE_MESSAGE = (
    "Extraction stopped before it finished — the worker reading this document "
    "was interrupted. The file is still stored; use Re-parse to try again."
)


def reap_stalled_parses(
    db: Session, *, now: datetime | None = None, stall_seconds: int | None = None
) -> int:
    """Fail invoices stranded in ``processing``, and return how many.

    :func:`process_invoice` writes its own failures to the row, so the status is
    an outcome for every error it can catch. It cannot catch the process ceasing
    to exist. ``PROCESSING`` is committed *before* anything is read — deliberately,
    so a crash cannot look like a successful parse — and the child holding a
    decoded PDF is exactly what the OOM killer picks, what the 240s hard time
    limit kills, and what a redeploy stops mid-document. No ``except`` runs in any
    of those, so the row keeps the status forever.

    Forever is the whole defect, and it is silent in both directions at once.
    ``PROCESSING`` is in :data:`~app.models.invoice.UNREADABLE_STATUSES`, so the
    GSTR-1, the period's output tax, the credit pool, the reconciliation and the
    supplier's exposure all skip the row — correctly, because nothing has read
    it. But the dashboard's needs-review count is ``PARSED`` plus ``FAILED``, and
    the register renders the status as a neutral "Processing" chip. So the one
    document that is missing from the return is the one document the product
    shows as work in hand, and there is no screen on which it is ever counted,
    listed or complained about. A business under-declares a supply and is told
    the month is clean.

    ``FAILED`` is the status this should have reached, and reaching it is what
    makes the row visible: it lands in the needs-review count, renders as a red
    chip, carries a reason, and — since ``FAILED`` is also unreadable — changes
    not one rupee of any return in the process. The uploaded file was committed
    before the parse ever started, so nothing has been lost and ``reparse`` is
    still the fix; this only stops the product from waiting on a worker that is
    not coming back.

    ``updated_at`` is the clock, because the database maintains it and the claim
    on the row is itself a write: a task that retries re-stamps it, so a parse
    being legitimately re-attempted is never mistaken for a dead one. The
    threshold is :data:`~app.core.config.Settings.invoice_parse_stall_seconds`,
    which is set well above what any legitimate parse can take.

    Idempotent, tenant-agnostic and safe to run on a schedule — it is a sweep
    over an operational state, not over anybody's books.
    """
    now = now or datetime.now(UTC)
    seconds = (
        settings.invoice_parse_stall_seconds if stall_seconds is None else stall_seconds
    )
    cutoff = now - timedelta(seconds=seconds)

    stalled_filter = [
        Invoice.status == InvoiceStatus.PROCESSING,
        Invoice.deleted_at.is_(None),
        Invoice.updated_at < cutoff,
    ]
    stalled_ids = list(
        db.scalars(select(Invoice.id).where(*stalled_filter)).all()
    )
    if stalled_ids:
        # Re-check the status: a concurrent ``process_invoice`` or reparse
        # may have moved the row out of PROCESSING between the SELECT above
        # and this UPDATE.  Without the guard a successfully parsed invoice
        # would be overwritten with FAILED.
        db.execute(
            update(Invoice)
            .where(
                Invoice.id.in_(stalled_ids),
                Invoice.status == InvoiceStatus.PROCESSING,
            )
            .values(status=InvoiceStatus.FAILED, parse_error=STALLED_PARSE_MESSAGE)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        logger.warning(
            "Reaped stalled invoices",
            extra={
                "count": len(stalled_ids),
                "stale_seconds": seconds,
                "invoice_ids": stalled_ids,
            },
        )
    return len(stalled_ids)


def tax_summary(
    db: Session, business_id: int, period: str | None = None
) -> dict[str, dict[str, int | Decimal]]:
    """Aggregate tax by direction, for one period or for all of them.

    One grouped query rather than a query per figure: the dashboard is the
    most-hit endpoint in the product and a business can hold tens of thousands
    of invoices.

    :func:`tax_summaries` is the same query over several periods at once, and
    is what the dashboard uses. This remains for the callers that want exactly
    one.

    Rows whose figures were never extracted are left out, because the returns
    leave them out — every status in
    :data:`~app.models.invoice.UNREADABLE_STATUSES`, not merely ``FAILED``. The
    dashboard's net liability is the number a business plans its cash around,
    and it has to be the number the GSTR-3B it files will show.

    Excluding only ``FAILED`` was the last place in the product still drawing
    that line in its own spot, and the two ways past it were not symmetric. A
    row still queued for a worker carries columns of zeros, so it moved no
    money and inflated the count. A row being *re-extracted* is the expensive
    one: ``process_invoice`` sets ``PROCESSING`` and commits before it reads
    anything, so the figures from the previous, successful read sit on it for
    the length of the parse — counted in full here, and left out of the return
    by ``filing`` and out of the credit pool by ``itc``.

    That is not only a dashboard that disagrees with itself for a few seconds.
    :func:`~app.services.filing.record_filing` stores *these* totals on the
    filed-return row, beside the document ``build_gstr1`` produced from the
    other rule — so a filing recorded while anything was mid-re-parse was
    written down with an invoice count and a taxable value that the return
    stored in the very same row does not contain. That record is what an
    assessment is answered from years later.

    The status counts on the dashboard are unaffected: those are lifetime
    counts of documents, and an unread one still needs attention.

    Three buckets, not two. ``sales`` and ``purchase`` are the tax that appears
    on invoices in each direction; ``credit`` is the part of the purchase side
    that may actually be claimed, which is a smaller and different number. Tax
    on a purchase is not credit if the credit is blocked under s.17(5) — a car,
    a staff lunch, a club membership — or if the supply is under reverse
    charge, where the supplier charges nothing and the buyer self-assesses.
    :mod:`app.services.itc` has always drawn that line; the dashboard's net
    liability is what it is drawn for, because subtracting a blocked credit
    from output tax tells a business it owes less than it does.
    """
    if period is None:
        return _summarise(db, business_id, group_by_period=False)[None]
    return _summarise(db, business_id, periods=[period], group_by_period=False)[None]


def tax_summaries(
    db: Session, business_id: int, periods: Sequence[str]
) -> dict[str, dict[str, dict[str, int | Decimal]]]:
    """:func:`tax_summary` for several periods, in one scan of the table.

    The dashboard shows the selected period beside six months of history, and
    it asked for each of them separately — seven aggregate scans of the
    invoice table on the most-hit endpoint in the product, six of them
    differing only in which month they filtered to. The period is the second
    column of ``ix_invoices_business_period``, so one ``IN`` over the seven
    reads the same span of the index the first of those seven already read.

    Periods with no invoices come back as empty buckets rather than being
    absent, so the chart keeps its gaps and the caller does not have to know
    which months were missing.
    """
    wanted = list(dict.fromkeys(periods))
    if not wanted:
        return {}
    found = _summarise(db, business_id, periods=wanted, group_by_period=True)
    return {period: found.get(period) or _blank_summary() for period in wanted}


def _blank_bucket() -> dict[str, int | Decimal]:
    return {
        "count": 0,
        "taxable_value": Decimal("0.00"),
        "cgst": Decimal("0.00"),
        "sgst": Decimal("0.00"),
        "igst": Decimal("0.00"),
        "cess": Decimal("0.00"),
        "total_value": Decimal("0.00"),
        "total_tax": Decimal("0.00"),
    }


def _blank_summary() -> dict[str, dict[str, int | Decimal]]:
    return {"sales": _blank_bucket(), "purchase": _blank_bucket(), "credit": _blank_bucket()}


# The money columns summed, in the order the select puts them and the order the
# rows are unpacked in. One tuple, so the two cannot drift.
_MONEY = ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value")


def _summarise(
    db: Session,
    business_id: int,
    *,
    periods: Sequence[str] | None = None,
    group_by_period: bool,
) -> dict[str | None, dict[str, dict[str, int | Decimal]]]:
    """The grouped scan behind both entry points, keyed by period.

    ``group_by_period`` decides whether the period reaches the ``GROUP BY`` or
    only the ``WHERE``: a caller asking about one period wants its three
    buckets under a single key, and gets ``None`` for it.
    """
    conditions = [
        Invoice.business_id == business_id,
        Invoice.deleted_at.is_(None),
        Invoice.status.not_in(UNCOUNTABLE_STATUSES),
    ]
    if periods:
        conditions.append(
            Invoice.period == periods[0] if len(periods) == 1 else Invoice.period.in_(periods)
        )

    # The same test ``itc.summarise`` applies before pooling a purchase into
    # available credit, expressed in SQL so the claimable totals come back from
    # the same grouped scan rather than a second pass over the table.
    claims_credit = and_(
        Invoice.itc_eligible.is_(True), Invoice.reverse_charge.is_(False)
    )

    def _summed(name: str):
        return func.coalesce(func.sum(getattr(Invoice, name)), 0)

    def _summed_if_claimable(name: str):
        return func.coalesce(
            func.sum(case((claims_credit, getattr(Invoice, name)), else_=0)), 0
        )

    grouping = [Invoice.period, Invoice.invoice_type] if group_by_period else [Invoice.invoice_type]
    rows = db.execute(
        select(
            *grouping,
            func.count(Invoice.id),
            *(_summed(name) for name in _MONEY),
            func.count(case((claims_credit, Invoice.id))),
            *(_summed_if_claimable(name) for name in _MONEY),
        )
        .where(*conditions)
        .group_by(*grouping)
    ).all()

    def _fill(bucket: dict, count, money) -> None:
        bucket["count"] = int(count)
        for name, value in zip(_MONEY, money, strict=True):
            bucket[name] = Decimal(str(value))
        bucket["total_tax"] = (
            bucket["cgst"] + bucket["sgst"] + bucket["igst"] + bucket["cess"]
        )

    summaries: dict[str | None, dict[str, dict[str, int | Decimal]]] = {}
    if not group_by_period:
        summaries[None] = _blank_summary()

    width = len(_MONEY)
    for row in rows:
        if group_by_period:
            row_period, invoice_type, count, *rest = row
        else:
            row_period = None
            invoice_type, count, *rest = row
        summary = summaries.setdefault(row_period, _blank_summary())
        key = invoice_type.value if hasattr(invoice_type, "value") else str(invoice_type)
        _fill(summary.setdefault(key, _blank_bucket()), count, rest[:width])
        # Only a purchase can carry credit; a sale's claimable columns are the
        # same arithmetic over rows that never had credit to begin with.
        if key == InvoiceType.PURCHASE.value:
            _fill(summary["credit"], rest[width], rest[width + 1 :])
    return summaries
