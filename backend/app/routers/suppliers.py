"""Suppliers and their compliance scores."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, require_writer
from app.core.params import Offset, RowId
from app.core.rate_limit import RateLimit
from app.core.sanitize import search_pattern
from app.models.business import Business
from app.models.supplier import RiskLevel, Supplier
from app.schemas.supplier import (
    RescoreOut,
    SupplierDetailOut,
    SupplierListOut,
    SupplierOut,
    SupplierScoreOut,
)
from app.services import gst_calendar, supplier_score

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

_read_limit = RateLimit("supplier_read", "240/minute")
# Rescoring walks every supplier's filing history and rewrites their row. It is
# an occasional maintenance action, not something a screen calls on render.
_rescore_limit = RateLimit("supplier_rescore", "10/minute")


@router.get(
    "",
    response_model=SupplierListOut,
    summary="Suppliers for this tenant, riskiest first",
    description=(
        "Ordered by compliance score ascending, with unrated suppliers last. The "
        "list exists to answer 'who should I worry about', and a supplier with no "
        "history is not an answer to that — they are simply unmeasured, which is "
        "why an unrated score is `null` rather than zero.\n\n"
        "`search` matches the GSTIN, legal name or trade name. `%` and `_` in the "
        "term are matched literally rather than as wildcards."
    ),
    dependencies=[Depends(_read_limit)],
)
def list_suppliers(
    risk_level: RiskLevel | None = Query(
        default=None, description="Restrict to `low`, `medium`, `high` or `unknown`."
    ),
    search: str | None = Query(
        default=None, max_length=100, description="Substring of the GSTIN or either name."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size, 1-200."),
    offset: Offset = 0,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> SupplierListOut:
    """Suppliers for this tenant, riskiest first.

    Ordered by score ascending with unrated suppliers last: the list exists to
    answer "who should I worry about", and a supplier with no history is not an
    answer to that — they are simply unmeasured.
    """
    conditions = [Supplier.business_id == business.id, Supplier.deleted_at.is_(None)]
    if risk_level is not None:
        conditions.append(Supplier.risk_level == risk_level)
    pattern = search_pattern(search)
    if pattern:
        conditions.append(
            Supplier.gstin.ilike(pattern, escape="\\")
            | Supplier.legal_name.ilike(pattern, escape="\\")
            | Supplier.trade_name.ilike(pattern, escape="\\")
        )

    total = int(db.scalar(select(func.count(Supplier.id)).where(*conditions)) or 0)
    rows = db.scalars(
        select(Supplier)
        .where(*conditions)
        .order_by(
            # NULL scores sort last regardless of the dialect's default.
            (Supplier.compliance_score.is_(None)).asc(),
            Supplier.compliance_score.asc(),
            Supplier.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()

    return SupplierListOut(
        items=[SupplierOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _owned_supplier(db: Session, business: Business, supplier_id: int) -> Supplier:
    """A supplier belonging to this tenant, or 404.

    404 rather than 403 outside the tenant: a 403 confirms the id exists, which
    leaks that another business buys from this supplier.
    """
    found = db.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.business_id == business.id,
            Supplier.deleted_at.is_(None),
        )
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supplier {supplier_id} not found. Refresh the supplier list and try again.",
        )
    return found


@router.post(
    "/rescore",
    response_model=RescoreOut,
    summary="Recompute every supplier's score from stored history",
    description=(
        "Exists because the weighting is expected to change: when it does, "
        "existing suppliers should reflect the new model without anyone "
        "re-running a year of reconciliations.\n\n"
        "Walks every supplier in the tenant, so it is limited tightly and is not "
        "something a screen should call on render."
    ),
    dependencies=[Depends(_rescore_limit), Depends(require_writer)],
)
def rescore(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> RescoreOut:
    """Recompute every supplier's score from their stored history.

    Exists because the weighting is expected to change: when it does, existing
    suppliers should reflect the new model without anyone re-running a year of
    reconciliations.
    """
    scores = supplier_score.rescore_all(db, business.id, as_of_period=period)
    return RescoreOut(
        rescored=len(scores),
        items=[SupplierScoreOut.model_validate(score.as_dict()) for score in scores],
    )


@router.get(
    "/{supplier_id}",
    response_model=SupplierDetailOut,
    summary="One supplier, with the score's working and the money at stake",
    description=(
        "`score_detail` shows every component that produced the score, so a "
        "number that decides whether to hold a payment can be explained to the "
        "supplier. `exposure` is the ITC currently resting on their invoices.\n\n"
        "404 rather than 403 outside the tenant: a 403 confirms the id exists, "
        "which leaks that another business buys from this supplier."
    ),
    responses={404: {"description": "No such supplier in this tenant."}},
    dependencies=[Depends(_read_limit)],
)
def get_supplier(
    supplier_id: RowId,
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> SupplierDetailOut:
    """One supplier, with the score's working and the money resting on them."""
    supplier = _owned_supplier(db, business, supplier_id)
    score = supplier_score.score_supplier(supplier, as_of_period=period)
    exposure = supplier_score.exposure(db, business.id, supplier)

    return SupplierDetailOut(
        **SupplierOut.model_validate(supplier).model_dump(),
        score_detail=SupplierScoreOut.model_validate(score.as_dict()),
        exposure=exposure.as_dict(),
    )
