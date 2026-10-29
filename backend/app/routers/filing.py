"""Filing preparation: validate a period, generate the return, export it."""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, require_writer
from app.core.params import Slug
from app.core.rate_limit import RateLimit
from app.core.sanitize import content_disposition
from app.models.business import Business
from app.models.gstr_return import GSTRReturn, ReturnType
from app.models.invoice import InvoiceType
from app.models.mixins import MONEY_MAX
from app.schemas.filing import (
    FiledReturnOut,
    FilingPreviewOut,
    FilingStatusItemOut,
    FilingStatusOut,
    LateFeeOut,
    RecordFilingIn,
    ValidationReportOut,
)
from app.services import filing as filing_service
from app.services import gst_calendar, invoice_service
from app.services import late_fee as late_fee_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/filing", tags=["filing"])

_read_limit = RateLimit("filing_read", "120/minute")
# An export builds the whole return and serialises it. Heavier than a preview,
# and a download is something a person triggers rather than a screen.
_export_limit = RateLimit("filing_export", "30/minute")
# Recording a filing rebuilds the return to store alongside it, and it is an
# action a person takes a handful of times a month.
_record_limit = RateLimit("filing_record", "20/minute")

# How many completed periods the status endpoint reports on. Six months covers
# the reconciliation history the dashboard already shows, and is well past the
# point where an unfiled return is news rather than a reminder.
STATUS_PERIODS = 6

# The returns a business files, addressable in a path.
_FILABLE = {rt.value: rt for rt in gst_calendar.DUE_DAY}

# Which direction of invoice each return is built from.
_DIRECTION = {
    "gstr1": InvoiceType.SALES,
    "gstr3b": InvoiceType.SALES,
    "purchases": InvoiceType.PURCHASE,
}


def _resolve_period(period: str | None) -> str:
    return period or invoice_service.month_of()


def _preview_out(
    db: Session, business: Business, period: str, return_type: ReturnType
) -> FilingPreviewOut:
    """Serialize what ``filing_service.preview`` built.

    Both preview routes go through here rather than each composing a build and
    a validation of their own. That composition is what quietly cost a second
    read of the period — the two halves want the same invoices, and only the
    service can hand them the same list.
    """
    built = filing_service.preview(db, business, period, return_type)
    return FilingPreviewOut(
        period=built.period,
        return_type=built.return_type,
        document=built.document,
        validation=ValidationReportOut.model_validate(built.validation.as_dict()),
    )


@router.get(
    "/validate",
    response_model=ValidationReportOut,
    summary="Everything that would stop a period being filed",
    description=(
        "Separates errors — which the portal will reject — from warnings, which "
        "merely ought to be fixed. A GSTIN that does not checksum is an error; a "
        "missing HSN code on a small-value line is a warning.\n\n"
        "Runs over sales by default, because that is what GSTR-1 is built from. "
        "Purchases are validated too — a supplier GSTIN that does not checksum is "
        "a credit that will never match — but they are asked for explicitly."
    ),
    dependencies=[Depends(_read_limit)],
)
def validate(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    invoice_type: InvoiceType = Query(default=InvoiceType.SALES),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ValidationReportOut:
    """Everything that would stop a period being filed, and what merely ought to be fixed.

    Runs over sales by default, because that is what GSTR-1 is built from.
    Purchases are validated too — a supplier GSTIN that does not checksum is a
    credit that will never match — but they are asked for explicitly.
    """
    report = filing_service.validate_period(
        db, business, _resolve_period(period), invoice_type=invoice_type
    )
    return ValidationReportOut.model_validate(report.as_dict())


@router.get(
    "/gstr1",
    response_model=FilingPreviewOut,
    summary="GSTR-1 for a period, in the portal's JSON shape",
    description=(
        "The outward-supplies return built from this period's sales invoices, "
        "with its B2B, B2CL and B2CS blocks and the HSN summary, plus the "
        "validation report for the same period so a caller does not need two "
        "round trips to know whether it is fileable."
    ),
    dependencies=[Depends(_read_limit)],
)
def preview_gstr1(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> FilingPreviewOut:
    """GSTR-1 for a period, in the portal's JSON shape, with its validation."""
    return _preview_out(db, business, _resolve_period(period), ReturnType.GSTR1)


@router.get(
    "/gstr3b",
    response_model=FilingPreviewOut,
    summary="GSTR-3B pre-filled from the reconciled position",
    description=(
        "The monthly summary return: outward tax from sales, eligible ITC from "
        "the reconciliation rather than from the books alone, and the reversals "
        "that follow from it — which is the difference between a 3B that matches "
        "the portal's own figures and one that invites a notice.\n\n"
        "Returned with the period's validation report."
    ),
    dependencies=[Depends(_read_limit)],
)
def preview_gstr3b(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> FilingPreviewOut:
    """GSTR-3B pre-filled from the reconciled position, with its validation."""
    return _preview_out(db, business, _resolve_period(period), ReturnType.GSTR3B)


def _standing_out(standing: filing_service.ReturnStanding) -> FilingStatusItemOut:
    return FilingStatusItemOut(
        period=standing.period,
        return_type=standing.return_type.value,
        due_date=standing.due_date,
        filed=standing.filed,
        filed_on=standing.filed_on,
        arn=standing.arn,
        filed_late=standing.filed_late,
        days_until_due=standing.days_until_due,
    )


@router.get(
    "/status",
    response_model=FilingStatusOut,
    summary="Which returns are filed, which are due, and which are late",
    description=(
        "The last six completed periods, each with its GSTR-1 and GSTR-3B. The "
        "current month is not listed: a return covers a whole month and the "
        "portal does not open it until that month is over.\n\n"
        "`days_until_due` goes negative once the date has passed, and "
        "`filed_late` stays true for a return that was filed after its due date "
        "— the clock stops at filing, so a return filed a week late does not go "
        "on getting later.\n\n"
        "Dates are Indian. A deadline falls at the end of the day in India, not "
        "wherever the server happens to run."
    ),
    dependencies=[Depends(_read_limit)],
)
def filing_status(
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> FilingStatusOut:
    """Which returns are filed, which are due, and which are late."""
    today = gst_calendar.today_ist()
    periods = gst_calendar.completed_periods(today, STATUS_PERIODS)
    lines = filing_service.standings(db, business.id, periods=periods, as_of=today)
    return FilingStatusOut(
        as_of=today,
        # Newest period first: the one a business is about to file is the one
        # they came to look at.
        items=[_standing_out(line) for line in reversed(lines)],
    )


@router.get(
    "/{return_type}/late-fee",
    response_model=LateFeeOut,
    summary="Late fee and interest owed on a period's return",
    description=(
        "`return_type` is `gstr1` or `gstr3b`. Section 47's late fee applies to "
        "both; Section 50's interest applies only to GSTR-3B, since that is the "
        "only return a cash payment runs through.\n\n"
        "While the return is unfiled, this is a running projection as of today "
        "that grows by the day — `projected` is true and `filed_on` is null. "
        "Once `POST /filing/{return_type}/filed` has recorded it, the same "
        "figures are the amount actually run up, frozen at the filing date.\n\n"
        "`previous_year_turnover` sets which late-fee cap applies; omitted, the "
        "highest cap is used so the estimate is never understated. `is_nil` "
        "overrides the nil-return guess this makes from the period's invoice "
        "counts, for a business that knows it filed nil despite invoices still "
        "on file."
    ),
    responses={404: {"description": "Unknown return type."}},
    dependencies=[Depends(_read_limit)],
)
def late_fee(
    return_type: Slug,
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    is_nil: bool | None = Query(default=None),
    # Declared and bounded like every other money figure in a query string
    # rather than taken as a string and parsed here, which is what it used to
    # be. Three inputs got through that hand-rolled parse:
    #
    # ``Decimal("nan")`` constructs without raising — only *arithmetic* on it
    # raises — so the try/except around the parse caught nothing and the
    # InvalidOperation surfaced two layers down, inside ``turnover_tier``'s
    # comparison, as a 500.
    #
    # A negative turnover parsed cleanly and then matched the *first* tier,
    # handing back the lowest cap. That is the one direction ``turnover_tier``
    # documents as unacceptable: understating a cap tells a business it is
    # covered and the shortfall notice arrives weeks later.
    #
    # And an exponent like ``1E+999999999`` was only harmless by luck — it
    # landed on the highest tier. ``le`` is what makes that a decision.
    previous_year_turnover: Decimal | None = Query(
        default=None,
        ge=0,
        le=MONEY_MAX,
        description="Decimal rupees. Omitted uses the highest cap tier.",
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> LateFeeOut:
    """Late fee and interest owed on a period's return, as of today."""
    kind = _FILABLE.get(return_type.lower())
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown return type '{return_type}'. Expected one of: "
            + ", ".join(sorted(_FILABLE)),
        )

    result = late_fee_service.estimate(
        db,
        business,
        _resolve_period(period),
        kind,
        is_nil=is_nil,
        previous_year_turnover=previous_year_turnover,
    )
    return LateFeeOut(**result.as_dict())


@router.post(
    "/{return_type}/filed",
    response_model=FiledReturnOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record that a return was filed on the portal",
    description=(
        "`return_type` is `gstr1` or `gstr3b`. This product prepares and exports "
        "a return; the portal is where it is submitted, and nothing here can "
        "observe that — so the business says so, and until they do the return "
        "looks exactly like one that was never filed.\n\n"
        "That is not only bookkeeping: the deadline alerting reads this, so a "
        "filing nobody records is a business that keeps being told it is late.\n\n"
        "Idempotent per period and return type. Recording the same period again "
        "corrects the ARN or the date rather than filing twice, so this is how a "
        "reference that was not to hand at the time gets added later.\n\n"
        "The ARN is optional for that reason. It is the proof the filing "
        "happened, but refusing the record without it would leave the alert "
        "firing for a return that is genuinely filed. Leaving it out of a "
        "later call does not clear a reference already recorded — only "
        "supplying a different one replaces it."
    ),
    responses={
        404: {"description": "Unknown return type."},
        422: {"description": "The filing could not have happened as described."},
    },
    dependencies=[Depends(_record_limit), Depends(require_writer)],
)
def record_filed(
    return_type: Slug,
    payload: RecordFilingIn,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> FiledReturnOut:
    """Record that a return was filed on the portal.

    Idempotent per period and return type: recording the same period again
    corrects the reference rather than filing a second time.
    """
    kind = _FILABLE.get(return_type.lower())
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown return type '{return_type}'. Expected one of: "
            + ", ".join(sorted(_FILABLE)),
        )

    try:
        record = filing_service.record_filing(
            db,
            business,
            payload.period,
            kind,
            arn=payload.arn,
            filed_on=payload.filed_on,
        )
    except filing_service.FilingNotRecordable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return _filed_out(record)


@router.delete(
    "/{return_type}/filed",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Withdraw a filing recorded by mistake",
    description=(
        "The way back out of `POST /filing/{return_type}/filed`, for a filing "
        "recorded against the wrong period or the wrong return. Recording again "
        "corrects a date or an ARN; it cannot say the return was never filed.\n\n"
        "The period becomes unfiled again: its deadline alert reopens on the next "
        "sweep and its late fee goes back to projecting. The record is kept, "
        "soft-deleted, and the period can be recorded again afterwards."
    ),
    responses={
        204: {"description": "Withdrawn."},
        404: {"description": "Unknown return type, or no filing recorded for that period."},
    },
    dependencies=[Depends(_record_limit), Depends(require_writer)],
)
def withdraw_filed(
    return_type: Slug,
    period: str = Query(pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> None:
    """Withdraw a filing recorded by mistake."""
    kind = _FILABLE.get(return_type.lower())
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown return type '{return_type}'. Expected one of: "
            + ", ".join(sorted(_FILABLE)),
        )
    if filing_service.withdraw_filing(db, business, period, kind) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {kind.value} filing is recorded for {period}.",
        )


def _filed_out(record: GSTRReturn) -> FiledReturnOut:
    due = record.due_date
    filed_at = record.filed_at
    return FiledReturnOut(
        id=record.id,
        period=record.period,
        return_type=record.return_type.value,
        status=record.status.value,
        arn=record.arn,
        filed_at=filed_at,
        due_date=due,
        invoice_count=record.invoice_count,
        total_taxable_value=record.total_taxable_value,
        total_cgst=record.total_cgst,
        total_sgst=record.total_sgst,
        total_igst=record.total_igst,
        total_cess=record.total_cess,
        filed_late=(
            gst_calendar.ist_date(filed_at) > gst_calendar.ist_date(due)
            if filed_at and due
            else False
        ),
    )


@router.get(
    "/export/{return_type}.{extension}",
    summary="Download a period as JSON for the portal, or CSV for a human",
    description=(
        "`return_type` is `gstr1`, `gstr3b` or `purchases`; `extension` is `json` "
        "or `csv`. Purchases are CSV only — there is no portal JSON shape for a "
        "purchase register.\n\n"
        "A download rather than a JSON body: this file goes into the government's "
        "offline utility or a spreadsheet, and it should arrive named for the "
        "GSTIN and period it covers rather than as `download (3)`. CSV carries a "
        "UTF-8 BOM, because Excel reads a plain UTF-8 CSV as Latin-1 and mangles "
        "every trade name with a rupee sign in it.\n\n"
        "Exports regardless of validation errors, on purpose. A business that "
        "wants to see what its half-finished GSTR-1 looks like is entitled to; "
        "`/filing/validate` is what says whether to file it."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "The file, as an attachment.",
            "content": {"application/json": {}, "text/csv": {}},
        },
        400: {"description": "Purchases were requested as JSON."},
        404: {"description": "Unknown return type or format."},
    },
    dependencies=[Depends(_export_limit)],
)
def export(
    return_type: Slug,
    extension: Slug,
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> Response:
    """Download a period as JSON for the portal, or CSV for a human.

    A download rather than a JSON body: this file goes into the government's
    offline utility or a spreadsheet, and it should arrive named for the GSTIN
    and period it covers rather than as ``download (3)``.

    Exports regardless of validation errors, on purpose. A business that wants
    to see what its half-finished GSTR-1 looks like is entitled to; the
    validation endpoint is what says whether to file it, and the preview
    endpoints return both together.
    """
    resolved = _resolve_period(period)
    kind = return_type.lower()
    fmt = extension.lower()

    if kind not in _DIRECTION:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown return type '{return_type}'. Expected one of: "
            + ", ".join(sorted(_DIRECTION)),
        )
    if fmt not in ("json", "csv"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{extension}' is not a supported export format. Use .json or .csv.",
        )

    filename = filing_service.filename_for(business, resolved, kind, fmt)
    logger.info(
        "Filing export",
        extra={
            "business_id": business.id,
            "period": resolved,
            "return_type": kind,
            "export_format": fmt,
            "export_filename": filename,
        },
    )
    headers = {"Content-Disposition": content_disposition(filename)}

    if fmt == "csv":
        body = filing_service.to_csv(db, business, resolved, _DIRECTION[kind])
        # UTF-8 BOM: Excel reads a plain UTF-8 CSV as Latin-1 and mangles every
        # trade name with a rupee sign or a non-ASCII character in it.
        return Response(
            content="﻿" + body,
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )

    if kind == "gstr3b":
        document = filing_service.build_gstr3b(db, business, resolved)
    elif kind == "gstr1":
        document = filing_service.build_gstr1(db, business, resolved)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Purchases can only be exported as CSV. Download the purchase "
                "register as .csv instead."
            ),
        )

    return Response(
        content=json.dumps(document, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers=headers,
    )
