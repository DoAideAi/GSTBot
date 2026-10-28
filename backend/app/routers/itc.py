"""The ITC position: what is available, what reverses, and what settles it."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, require_paid_tier
from app.core.rate_limit import RateLimit
from app.models.business import Business
from app.models.mixins import MONEY_MAX
from app.schemas.itc import (
    ITCSummaryOut,
    LapsingCreditListOut,
    Rule37Out,
    SetOffOut,
    SetOffRequest,
)
from app.services import gst_calendar, invoice_service, itc_deadline
from app.services import itc as itc_service

router = APIRouter(prefix="/itc", tags=["itc"])

_read_limit = RateLimit("itc_read", "120/minute")
# Pure arithmetic over the request body, no database. Cheap enough to leave
# generous, but still bounded — it is a POST anyone with a token can call.
_setoff_limit = RateLimit("itc_setoff", "240/minute")


@router.get(
    "",
    response_model=ITCSummaryOut,
    summary="The full ITC position for a period",
    description=(
        "What credit is available, what is blocked under s.17(5), what reverses "
        "under Rules 37, 42 and 43, and what is left.\n\n"
        "`exempt_turnover` and `total_turnover` are overridable because Rule 42 "
        "turns on exempt turnover, and the product can only infer that from "
        "sales invoices carrying no tax. A business with exempt supplies it does "
        "not invoice through DoAide GST knows the real number, and a reversal "
        "computed from the wrong denominator is worse than one the user "
        "supplied.\n\n"
        "`as_of` exists for the same reason a CA asks 'where did this stand at "
        "year end' — the 180-day clock has a different answer on every date."
    ),
    dependencies=[Depends(_read_limit), Depends(require_paid_tier)],
)
def get_itc_summary(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    # Bounded above for the same reason the stored amounts are: these two go
    # straight into the Rule 42 ratio and out through the paise quantize, and
    # ``1E+100`` in a query string was a 500 rather than a 422.
    exempt_turnover: Decimal | None = Query(default=None, ge=0, le=MONEY_MAX),
    total_turnover: Decimal | None = Query(default=None, ge=0, le=MONEY_MAX),
    as_of: date | None = Query(
        default=None, description="Date the 180-day clock is measured against"
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> ITCSummaryOut:
    """The full ITC position for a period.

    The turnover figures are overridable because Rule 42 turns on *exempt
    turnover*, and the product can only infer that from sales invoices that
    carry no tax. A business with exempt supplies it does not invoice through
    DoAide GST knows the real number, and a reversal computed from the wrong
    denominator is worse than one the user supplied.

    ``as_of`` exists for the same reason a CA asks "where did this stand at
    year end" — the 180-day clock has a different answer on every date.
    """
    period = period or invoice_service.month_of()
    summary = itc_service.summarise(
        db,
        business.id,
        period,
        as_of=as_of,
        exempt_turnover=exempt_turnover,
        total_turnover=total_turnover,
    )
    return ITCSummaryOut.model_validate(summary.as_dict())


@router.get(
    "/rule37",
    response_model=Rule37Out,
    summary="Purchases whose credit has reversed, or is about to",
    description=(
        "Rule 37 reverses the credit on a purchase left unpaid 180 days past the "
        "invoice date. This lists what has already crossed that line and what is "
        "approaching it.\n\n"
        "Deliberately *not* scoped to a period: the invoice that crosses 180 days "
        "is one from eight months ago, and a period filter would never surface it."
    ),
    dependencies=[Depends(_read_limit), Depends(require_paid_tier)],
)
def get_rule_37(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> Rule37Out:
    """Purchases whose credit has reversed, or is about to, for non-payment.

    Deliberately not scoped to a period: the invoice that crosses 180 days is
    one from eight months ago, and a period filter would never surface it.
    """
    invoices = itc_service.purchase_invoices(db, business.id, credit_only=True)
    return Rule37Out.model_validate(itc_service.rule_37(invoices, as_of=as_of).as_dict())


@router.get(
    "/lapsing",
    response_model=LapsingCreditListOut,
    summary="Credit approaching the s.16(4) claim deadline, by financial year",
    description=(
        "Input credit on purchases that has not been taken into a GSTR-3B, "
        "grouped by the financial year whose deadline governs it.\n\n"
        "Section 16(4) bars credit on an invoice after the 30th of November "
        "following the end of its financial year. Unlike every other reversal "
        "this API reports, it is permanent: the credit is not deferred past "
        "that date, it is extinguished, and no later filing recovers it.\n\n"
        "Years whose deadline has already passed are included, and flagged "
        "`expired`. A lapsed year is the most important row here, not the least."
    ),
    dependencies=[Depends(_read_limit), Depends(require_paid_tier)],
)
def get_lapsing_credit(
    as_of: date | None = Query(
        default=None, description="Date the deadline is measured against"
    ),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> LapsingCreditListOut:
    """Unclaimed credit by financial year, soonest s.16(4) deadline first.

    No ``since_period`` floor is passed, unlike the alerting: a business asking
    this question wants the whole register, including the years from before
    they signed up. The caution the sweep applies is about interrupting someone
    with a figure the product cannot stand behind, and nobody is being
    interrupted here.
    """
    rows = itc_deadline.lapsing_credit(db, business.id, as_of=as_of)
    at_risk = sum(
        (row.total for row in rows if not row.expired), start=Decimal("0")
    )
    expired = sum((row.total for row in rows if row.expired), start=Decimal("0"))
    return LapsingCreditListOut.model_validate(
        {
            "years": [row.as_dict() for row in rows],
            "total_at_risk": str(at_risk),
            "total_expired": str(expired),
            "lead_days": itc_deadline.LEAD_DAYS,
        }
    )


@router.post(
    "/set-off",
    response_model=SetOffOut,
    summary="Apply a credit against a liability in the statutory order",
    description=(
        "IGST credit is exhausted first, against IGST, then CGST, then SGST; "
        "CGST credit can never discharge an SGST liability, or the reverse. The "
        "response shows the utilisation per head plus what has to be paid in "
        "cash and what carries forward.\n\n"
        "Pure arithmetic over what the caller sends — no database is read — so a "
        "CA can try a what-if against figures that are not in the books yet."
    ),
    dependencies=[Depends(_setoff_limit)],
)
def compute_set_off(
    payload: SetOffRequest,
    _business: Business = Depends(get_current_business),
) -> SetOffOut:
    """Apply a given credit against a given liability, in the statutory order.

    Pure arithmetic over what the caller sends — no database — so a CA can try
    a what-if against figures that are not in the books yet.

    The tenant is resolved and then not used, which is the point: reading
    nothing is what made this the one business route that never asked who was
    calling. It was the only endpoint outside ``/health*`` and ``/meta/*``
    answering 200 without a token — against a published contract that says
    every other one needs a bearer token, and against its own limiter, which
    is spelled ``by="identity"`` and therefore fell back to keying anonymous
    callers by address. What that left open is not a data leak, because there
    is no data here; it is an unauthenticated POST that decodes a body,
    constructs eight ``Decimal`` s and runs the settlement, at 240 a minute per
    address, on an endpoint whose own comment already described it as one
    "anyone with a token can call".
    """
    credit = itc_service.TaxHeads(
        igst=payload.credit_igst,
        cgst=payload.credit_cgst,
        sgst=payload.credit_sgst,
        cess=payload.credit_cess,
    )
    liability = itc_service.TaxHeads(
        igst=payload.liability_igst,
        cgst=payload.liability_cgst,
        sgst=payload.liability_sgst,
        cess=payload.liability_cess,
    )
    return SetOffOut.model_validate(itc_service.set_off(credit, liability).as_dict())
