"""GSTR-2B import and the reconciliation runs that follow it."""
from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import (
    get_current_business,
    get_current_user,
    require_paid_tier,
    require_writer,
)
from app.core.params import Offset, RowId
from app.core.rate_limit import RateLimit
from app.core.sanitize import content_disposition, safe_filename
from app.models.business import Business
from app.models.gstr_return import GSTRReturn, ReturnType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.models.report_purchase import ReportPurchase
from app.models.user import User
from app.schemas.reconciliation import (
    GSTR2BImportOut,
    ImportedPeriodsOut,
    ReconcileRequest,
    ReconciliationDetailOut,
    ReconciliationListOut,
    ReconciliationRunOut,
    ReportOrderOut,
    ReportOrderRequest,
    ReportPurchaseOut,
    ReportVerifyRequest,
)
from app.services import (
    gst_calendar,
    gstr2b,
    razorpay_client,
    reconciliation,
    reconciliation_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

ALLOWED_EXTENSIONS = (".json", ".csv", ".txt")

# A 2B import parses a whole month of the portal's JSON and rewrites the stored
# statement; a run matches every purchase in the period against it. Both are
# heavier than a read, and neither is something a person does repeatedly.
_import_limit = RateLimit("gstr2b_import", "20/minute")
_run_limit = RateLimit("reconcile_run", "30/minute")
_read_limit = RateLimit("reconcile_read", "240/minute")
# Paying is a handful of calls per report; rendering one is a few hundred
# milliseconds of CPU per call, which is what the download bucket is sized for.
_report_order_limit = RateLimit("report_order", "10/minute")
_report_verify_limit = RateLimit("report_verify", "10/minute")
_report_download_limit = RateLimit("report_download", "30/minute")


@router.post(
    "/gstr2b/import",
    response_model=GSTR2BImportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Import a GSTR-2B statement",
    description=(
        "Takes the JSON the GST portal produces, or a CSV export of it.\n\n"
        "The period is read out of the file when the caller does not name one: "
        "the portal stamps the statement period into the download, and someone "
        "who has just clicked through three months of statements should not have "
        "to remember which one this was.\n\n"
        "Re-importing a period is routine and expected — the portal regenerates "
        "the 2B whenever a supplier files late — so the previous import is "
        "soft-deleted rather than dropped, and the response says "
        "`replaced_previous`. Invoices in the file that belong to *other* "
        "periods are reported in `other_periods` rather than treated as an "
        "error: those are late filings, and they reconcile against the month "
        "they belong to.\n\n"
        "A statement the portal addressed to a different GSTIN is refused. The "
        "2B is generated per registration, so one imported into the wrong "
        "tenant reconciles to nothing on either side and reports the whole "
        "period's credit at risk — which reads as a supplier catastrophe and "
        "is a mis-click."
    ),
    responses={
        201: {"description": "Imported. Run a reconciliation next."},
        400: {"description": "The uploaded file is empty."},
        413: {"description": "Larger than `MAX_UPLOAD_MB`."},
        415: {"description": "Not a JSON or CSV file."},
        422: {
            "description": (
                "Not a readable GSTR-2B, it contained no invoices, no period "
                "could be determined from it, or it is addressed to another "
                "GSTIN."
            )
        },
    },
    dependencies=[Depends(_import_limit), Depends(require_writer), Depends(require_paid_tier)],
)
async def import_gstr2b(
    file: UploadFile = File(..., description="GSTR-2B download: portal JSON or CSV export"),
    period: str | None = Form(
        default=None,
        pattern=gst_calendar.PERIOD_PATTERN,
        description="YYYY-MM; taken from the file when omitted",
        examples=["2026-04"],
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> GSTR2BImportOut:
    """Import a GSTR-2B for a period.

    The period is read out of the file when the caller does not name one: the
    portal stamps the statement period into the download, and a user who has
    just clicked through three months of statements should not have to keep
    track of which one this was.

    A period supplied by the caller is checked against the same pattern every
    other route spells a period with. This one was the only period input in the
    product without it, and it is the one that *writes* a period: the two the
    file itself can offer are derived from a date and a validated portal field,
    so the form value was the only way an unreal month could reach the column.
    ``2026-13`` stored a statement under a month that does not exist, which no
    later screen can reconcile or file; anything over seven characters is
    refused by the column itself on Postgres and silently kept whole by the
    SQLite the suite runs on — a 500 on the deployment and a green test.
    """
    filename = safe_filename(file.filename, fallback="gstr2b")
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"{filename} cannot be read as a GSTR-2B. Upload the JSON the GST "
                "portal downloads, or a CSV export of it."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{filename} is empty (0 bytes). It may still be downloading.",
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            # The size, but no advice about reducing it: a 2B is one portal
            # download for one registration for one month, and there is
            # nothing a user can re-export or split. Meeting this means the
            # deployment's limit is set below what a real statement weighs,
            # which is the operator's to raise, so the number is what to
            # report to them.
            detail=(
                f"{filename} is {len(content) / (1024 * 1024):.1f} MB, over the "
                f"{settings.max_upload_mb} MB limit. A GSTR-2B is rarely this "
                "large, so check it is the right file; if it is, send this "
                "message to support."
            ),
        )

    # Whose statement this is, before anything is read out of it. A 2B is
    # generated per registration and the portal stamps the GSTIN on it, so a
    # file addressed to somebody else is not this tenant's evidence about
    # anything — and importing one is the mistake a practice with several
    # clients on one login is placed to make.
    #
    # Refused rather than reconciled, because reconciling it looks like a
    # catastrophe rather than a mis-click: every purchase in the books comes
    # back missing from the statement, every document in the statement missing
    # from the books, and the period's entire credit is reported at risk. The
    # numbers are all correct and the conclusion is nonsense, and no screen
    # downstream has anything left to notice it with.
    addressee = gstr2b.recipient_gstin(content, filename)
    if addressee and addressee != business.gstin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This GSTR-2B is addressed to {addressee}, but you are signed in as "
                f"{business.gstin}. Import it under that registration instead."
            ),
        )

    try:
        records = gstr2b.parse(content, filename)
    except gstr2b.GSTR2BParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No invoices found in the file. Check that this is a GSTR-2B download.",
        )

    # Which period this statement is filed under, in order of authority: an
    # explicit form value, the period the portal stamped into the download,
    # then the most common invoice period in the file. The last is a guess, so
    # it breaks ties toward the latest month rather than on dict ordering —
    # late filings drag earlier months in, and the statement is about the
    # newest of them.
    stamped = next(
        (record.statement_period for record in records if record.statement_period), None
    )
    # The portal's stamp is the statement's own word on which month it covers,
    # so a form naming another month is a wrong file or a wrong pick, not a
    # preference. Letting the form win stored April's statement as May's,
    # silently replacing whatever May had on file, and reconciled both months'
    # credit against the wrong supplier filings. A file with no stamp — a CSV
    # export — still takes the period it is given.
    if period and stamped and period != stamped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{filename} is the GSTR-2B for {stamped}, but it was uploaded as "
                f"{period}. Pick {stamped}, or download the statement for {period} "
                "from the portal."
            ),
        )
    resolved = period or stamped
    if resolved is None:
        periods = [record.period for record in records if record.period]
        resolved = max(sorted(set(periods), reverse=True), key=periods.count) if periods else None
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Could not determine the period from the file. Re-upload and set the "
                "period explicitly."
            ),
        )

    had_previous = reconciliation.latest_gstr2b(db, business.id, resolved) is not None
    stored = reconciliation.store_gstr2b(
        db, business.id, resolved, records, source_filename=filename
    )

    logger.info(
        "GSTR-2B imported",
        extra={
            "business_id": business.id,
            "period": resolved,
            "record_count": len(records),
            "replaced_previous": had_previous,
            "source_filename": filename,
        },
    )

    other_periods = sorted(
        {record.period for record in records if record.period and record.period != resolved}
    )
    message = f"Imported {len(records)} invoices for {resolved}"
    if had_previous:
        message += " (replacing the previous import)"
    if other_periods:
        # Not an error: these are late filings, and they reconcile against the
        # month they belong to rather than this statement's month.
        message += (
            f". {len(other_periods)} other period(s) present: {', '.join(other_periods)}"
        )

    return GSTR2BImportOut(
        **{key: getattr(stored, key) for key in (
            "id", "period", "return_type", "status", "invoice_count",
            "total_taxable_value", "total_cgst", "total_sgst", "total_igst",
            "total_cess", "created_at",
        )},
        other_periods=other_periods,
        replaced_previous=had_previous,
        message=message,
    )


@router.get(
    "/gstr2b/periods",
    response_model=ImportedPeriodsOut,
    summary="Periods with a GSTR-2B on file",
    description="Newest first. What the period picker on the reconcile screen offers.",
    dependencies=[Depends(_read_limit)],
)
def list_imported_periods(
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ImportedPeriodsOut:
    """Periods with a GSTR-2B on file, newest first."""
    return ImportedPeriodsOut(items=reconciliation.periods_with_2b(db, business.id))


@router.post(
    "/run",
    response_model=ReconciliationDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reconcile a period against its GSTR-2B",
    description=(
        "Matches every purchase invoice in the period against the imported "
        "statement and classifies each one as matched, mismatched, missing in "
        "2B, missing in books, or a duplicate. The response carries the "
        "per-invoice report and the ITC split — what is safe to claim, and what "
        "is resting on an invoice the supplier has not filed.\n\n"
        "Runs inline: the caller is waiting on the answer, and this is "
        "arithmetic over rows already in the database — unlike parsing, it makes "
        "no network call that could rate-limit.\n\n"
        "Runs accumulate rather than overwrite. A period is reconciled again "
        "every time a supplier files late, and 'what did we know, and when' is "
        "the question an ITC reversal turns on months later."
    ),
    responses={
        201: {"description": "Reconciled. The report is in the response."},
        409: {
            "description": (
                "No GSTR-2B imported for that period, or a reconciliation is "
                "already running."
            )
        },
    },
    dependencies=[Depends(_run_limit), Depends(require_writer), Depends(require_paid_tier)],
)
def run(
    payload: ReconcileRequest,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ReconciliationDetailOut:
    """Reconcile a period's purchase register against its GSTR-2B.

    Runs inline. The caller is waiting on the answer, and matching a month of
    invoices is arithmetic over rows already in the database — unlike parsing,
    it makes no network call that could rate-limit.
    """
    try:
        completed = reconciliation.run_reconciliation(
            db, business.id, payload.period, tolerance=payload.tolerance
        )
    except reconciliation.NoGSTR2BImported as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except reconciliation.ConcurrentReconciliation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ReconciliationDetailOut.model_validate(completed)


@router.get(
    "",
    response_model=ReconciliationListOut,
    summary="Past reconciliation runs",
    description="Newest first, optionally filtered to one period. Counts only, no report.",
    dependencies=[Depends(_read_limit)],
)
def list_runs(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    limit: int = Query(default=20, ge=1, le=100),
    offset: Offset = 0,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ReconciliationListOut:
    """Past runs, newest first."""
    conditions = [
        ReconciliationRun.business_id == business.id,
        ReconciliationRun.deleted_at.is_(None),
    ]
    if period:
        conditions.append(ReconciliationRun.period == period)

    total = int(db.scalar(select(func.count(ReconciliationRun.id)).where(*conditions)) or 0)
    # Counts only, as the description promises — and so without ``report``,
    # the per-invoice findings, which for a busy period runs to thousands of
    # entries a row on a page of up to a hundred rows.
    rows = db.scalars(
        select(ReconciliationRun)
        .options(defer(ReconciliationRun.report))
        .where(*conditions)
        .order_by(ReconciliationRun.created_at.desc(), ReconciliationRun.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ReconciliationListOut(
        items=[ReconciliationRunOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/latest",
    response_model=ReconciliationDetailOut,
    summary="The most recent run for a period",
    description="The full run including its per-invoice report. This is what the UI shows.",
    responses={404: {"description": "That period has never been reconciled."}},
    dependencies=[Depends(_read_limit)],
)
def latest_run(
    period: str = Query(..., pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ReconciliationDetailOut:
    """The most recent run for a period, report included."""
    found = db.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.business_id == business.id,
            ReconciliationRun.period == period,
            ReconciliationRun.deleted_at.is_(None),
        )
        .order_by(ReconciliationRun.created_at.desc(), ReconciliationRun.id.desc())
        .limit(1)
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No reconciliation has been run for {period} yet. Import its "
                "GSTR-2B and run one."
            ),
        )
    return ReconciliationDetailOut.model_validate(found)


@router.get(
    "/{run_id}",
    response_model=ReconciliationDetailOut,
    summary="One run with its full report",
    description=(
        "404 rather than 403 outside the tenant: a 403 confirms the id exists, "
        "which leaks that another business ran a reconciliation."
    ),
    responses={404: {"description": "No such run in this tenant."}},
    dependencies=[Depends(_read_limit)],
)
def get_run(
    run_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ReconciliationDetailOut:
    """One run with its full per-invoice report.

    404 rather than 403 outside the tenant: a 403 confirms the id exists, which
    leaks that another business ran a reconciliation.
    """
    found = db.scalar(
        select(ReconciliationRun).where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.business_id == business.id,
            ReconciliationRun.deleted_at.is_(None),
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Reconciliation run {run_id} not found. Pick a run from this "
                "period's history instead."
            ),
        )
    return ReconciliationDetailOut.model_validate(found)


@router.get(
    "/gstr2b/{period}",
    response_model=GSTR2BImportOut,
    summary="The GSTR-2B currently on file for a period",
    description="The live import, with its totals. Superseded imports are not returned.",
    responses={404: {"description": "Nothing imported for that period."}},
    dependencies=[Depends(_read_limit)],
)
def get_imported_2b(
    period: str = Path(pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> GSTR2BImportOut:
    """The GSTR-2B currently on file for a period."""
    # The summary columns are the answer; ``data`` is the whole statement.
    found = db.scalar(
        select(GSTRReturn)
        .options(defer(GSTRReturn.data))
        .where(
            GSTRReturn.business_id == business.id,
            GSTRReturn.period == period,
            GSTRReturn.return_type == ReturnType.GSTR2B,
            GSTRReturn.deleted_at.is_(None),
        )
        .order_by(GSTRReturn.created_at.desc(), GSTRReturn.id.desc())
        .limit(1)
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No GSTR-2B imported for {period}. Download it from the GST "
                "portal and import it here."
            ),
        )
    return GSTR2BImportOut.model_validate(found)


# ---------------------------------------------------------------------------
# The paid PDF report
# ---------------------------------------------------------------------------


def _reportable_run(db: Session, business: Business, run_id: int) -> ReconciliationRun:
    """This tenant's run, completed — or the refusal that says why not.

    404 outside the tenant, as everywhere else here. 409 for a run that never
    completed: it has no findings, so there is nothing in it to pay for.
    """
    run = db.scalar(
        select(ReconciliationRun).where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.business_id == business.id,
            ReconciliationRun.deleted_at.is_(None),
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Reconciliation run {run_id} not found. Pick a run from this "
                "period's history instead."
            ),
        )
    if run.status is not ReconciliationStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This run is {run.status.value}, so it has no report yet. "
                "Run the reconciliation again and buy the report of that run."
            ),
        )
    return run


def _purchase_for(db: Session, business_id: int, run_id: int) -> ReportPurchase | None:
    # No deleted_at filter: a payment that has been redeemed once stays
    # redeemed, whatever later happens to the row.
    return db.scalar(
        select(ReportPurchase).where(
            ReportPurchase.business_id == business_id,
            ReportPurchase.run_id == run_id,
        ).limit(1)
    )


def _download_path(run_id: int) -> str:
    return f"/reconciliation/{run_id}/report.pdf"


@router.post(
    "/report/purchase",
    response_model=ReportOrderOut,
    summary="Start buying the PDF report of one run (Rs. 99)",
    description=(
        "Creates a Razorpay order for the run's report. When this business has "
        "already paid for it, no order is created and `already_purchased` is "
        "true: the report is downloaded again rather than charged for twice."
    ),
    responses={
        404: {"description": "No such run in this tenant."},
        409: {"description": "The run did not complete, so it has no report."},
        502: {"description": "Razorpay did not create the order. Safe to retry."},
        503: {"description": "Payment processing is not configured on this server."},
    },
    dependencies=[Depends(_report_order_limit), Depends(require_writer)],
)
def purchase_report(
    payload: ReportOrderRequest,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ReportOrderOut:
    run = _reportable_run(db, business, payload.run_id)
    if _purchase_for(db, business.id, run.id) is not None:
        return ReportOrderOut(run_id=run.id, already_purchased=True)

    if not razorpay_client.is_configured():
        logger.error(
            "Report checkout refused: Razorpay is not configured",
            extra={"business_id": business.id, "run_id": run.id},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Reports cannot be bought right now because payments are not "
                "available. Try again later, or contact support."
            ),
        )
    order = razorpay_client.create_order(
        amount_paise=razorpay_client.REPORT_PRICE_PAISE,
        receipt=razorpay_client.report_receipt(business.id, run.id),
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not start the payment. Try again, or contact support if "
                "this persists."
            ),
        )
    # Ties the order to the business and run, for the day someone says they
    # paid for a report they cannot download.
    logger.info(
        "Report order created",
        extra={
            "business_id": business.id,
            "run_id": run.id,
            "razorpay_order_id": order["id"],
            "amount_paise": order["amount"],
        },
    )
    return ReportOrderOut(
        run_id=run.id,
        already_purchased=False,
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        razorpay_key_id=settings.razorpay_key_id,
    )


_UNMATCHED_PAYMENT = (
    "This payment does not match the report it is being applied to. Contact "
    "support if you were charged."
)


@router.post(
    "/report/verify",
    response_model=ReportPurchaseOut,
    summary="Confirm a report payment, then download it from `download_path`",
    description=(
        "Checks Razorpay's signature, then asks Razorpay for the order and "
        "requires it to have been created for this business and run, at the "
        "report's price, and paid in full. Safe to call again with the same "
        "payment: a payment already recorded for this run is answered as a "
        "success, so a browser that lost the response can still get the file."
    ),
    responses={
        400: {"description": "The signature or the order does not match this report."},
        404: {"description": "No such run in this tenant."},
        409: {
            "description": (
                "The run did not complete, or this payment was already applied to "
                "a different run."
            )
        },
        502: {"description": "Razorpay could not be asked about the order. Safe to retry."},
    },
    dependencies=[Depends(_report_verify_limit), Depends(require_writer)],
)
def verify_report_payment(
    payload: ReportVerifyRequest,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
    current_user: User = Depends(get_current_user),
) -> ReportPurchaseOut:
    run = _reportable_run(db, business, payload.run_id)
    done = ReportPurchaseOut(run_id=run.id, purchased=True, download_path=_download_path(run.id))

    if not razorpay_client.verify_payment_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
    ):
        logger.warning(
            "Report payment signature verification failed",
            extra={
                "business_id": business.id,
                "user_id": current_user.id,
                "run_id": run.id,
                "razorpay_order_id": payload.razorpay_order_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Payment verification failed. Contact support if you were charged, "
                "or try the payment again."
            ),
        )

    def _recorded() -> ReportPurchase | None:
        return db.scalar(
            select(ReportPurchase).where(
                ReportPurchase.business_id == business.id,
                ReportPurchase.razorpay_payment_id == payload.razorpay_payment_id,
            )
        )

    def _already(existing: ReportPurchase) -> ReportPurchaseOut:
        if existing.run_id == run.id:
            return done
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This payment has already been applied to a different report.",
        )

    existing = _recorded()
    if existing is not None:
        return _already(existing)

    order = razorpay_client.fetch_order(payload.razorpay_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not confirm the payment with the payment provider. Try again "
                "in a moment — if you were charged, it will not be lost."
            ),
        )
    price = razorpay_client.REPORT_PRICE_PAISE
    problems = []
    if order.get("receipt") != razorpay_client.report_receipt(business.id, run.id):
        problems.append("receipt")
    if order.get("amount") != price:
        problems.append("amount")
    if order.get("status") != "paid" or (order.get("amount_paid") or 0) < price:
        problems.append("status")
    if problems:
        logger.warning(
            "Report payment refused: order does not match the request",
            extra={
                "business_id": business.id,
                "run_id": run.id,
                "razorpay_order_id": payload.razorpay_order_id,
                "mismatch": problems,
                "order_status": order.get("status"),
            },
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_UNMATCHED_PAYMENT)

    db.add(
        ReportPurchase(
            business_id=business.id,
            run_id=run.id,
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            amount_paise=price,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Checkout's handler and a retry of it can both get here with the same
        # payment; the unique constraint keeps one row, and the loser answers
        # from it.
        db.rollback()
        existing = _recorded()
        if existing is None:
            raise
        return _already(existing)

    logger.info(
        "Report purchased",
        extra={
            "business_id": business.id,
            "user_id": current_user.id,
            "run_id": run.id,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_order_id": payload.razorpay_order_id,
            "amount_paise": price,
        },
    )
    return done


@router.get(
    "/{run_id}/report.pdf",
    summary="Download the PDF report of a run this business has paid for",
    description=(
        "Rendered from what the run stored, so the same run always gives the "
        "same report. Downloadable again at no charge once bought."
    ),
    response_class=Response,
    responses={
        200: {"description": "The report, as an attachment.", "content": {"application/pdf": {}}},
        402: {"description": "This run's report has not been bought."},
        404: {"description": "No such run in this tenant."},
        409: {"description": "The run did not complete, so it has no report."},
    },
    dependencies=[Depends(_report_download_limit)],
)
def download_report(
    run_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> Response:
    run = _reportable_run(db, business, run_id)
    if _purchase_for(db, business.id, run.id) is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Buy this report to download it. It is Rs. 99, once, for this run.",
        )
    body = reconciliation_report.build_pdf(run, business)
    who = business.gstin or f"business-{business.id}"
    filename = f"reconciliation-{who}-{run.period}-run{run.id}.pdf"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(filename)},
    )
