"""Authenticated supplier queues and explicit, unsent handoffs."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business
from app.core.params import RowId
from app.core.rate_limit import RateLimit
from app.models.business import Business
from app.services import practice, supplier_followup

router = APIRouter(prefix="/practice", tags=["CA workspace"])
_read = RateLimit("supplier_followup", "60/minute")
_export = RateLimit("supplier_followup_export", "30/minute")


def selected(db, business, run_id, gstin):
    run = practice.scoped_run(db, business.id, run_id)
    if practice.is_stale(db, business.id, run):
        raise HTTPException(409, "The source data or latest run changed. Reconcile again "
                            "before preparing a supplier handoff.")
    reviews, _, _ = practice.review_summary(db, run)
    groups, _ = supplier_followup.groups(run, reviews)
    group = next((g for g in groups if g["gstin"] == gstin), None)
    if group is None:
        raise HTTPException(404, "No outstanding supplier follow-up found in this run.")
    return run, group


@router.get(
    "/runs/{run_id}/supplier-followups",
    summary="Group unresolved reconciliation findings by supplier",
    dependencies=[Depends(_read)],
)
def queue(run_id: RowId, response: Response, db: Session = Depends(get_db),
          business: Business = Depends(get_current_business)) -> dict:
    run = practice.scoped_run(db, business.id, run_id)
    reviews, _, _ = practice.review_summary(db, run)
    groups, unassigned = supplier_followup.groups(run, reviews)
    response.headers["Cache-Control"] = "no-store"
    return {"run_id": run.id, "period": run.period,
            "stale": practice.is_stale(db, business.id, run),
            "suppliers": groups, "unassigned": unassigned,
            "total": sum(g["count"] for g in groups)}


@router.get(
    "/runs/{run_id}/supplier-draft",
    summary="Prepare an editable supplier message without sending it",
    dependencies=[Depends(_read)],
)
def message(run_id: RowId, response: Response,
            gstin: str | None = Query(None, max_length=15, pattern=r"^[0-9A-Z]{15}$"),
            db: Session = Depends(get_db),
            business: Business = Depends(get_current_business)) -> dict:
    run, group = selected(db, business, run_id, gstin)
    response.headers["Cache-Control"] = "no-store"
    return supplier_followup.draft(run, business, group)


@router.get(
    "/runs/{run_id}/supplier-invoices.csv",
    summary="Export one supplier's outstanding invoice facts",
    dependencies=[Depends(_export)], response_class=Response,
)
def invoice_list(run_id: RowId,
                 gstin: str | None = Query(None, max_length=15, pattern=r"^[0-9A-Z]{15}$"),
                 draft_fingerprint: str | None = Query(None, pattern=r"^[0-9a-f]{64}$"),
                 db: Session = Depends(get_db),
                 business: Business = Depends(get_current_business)) -> Response:
    run, group = selected(db, business, run_id, gstin)
    if draft_fingerprint and draft_fingerprint != supplier_followup.fingerprint(run, group):
        raise HTTPException(409, "The outstanding findings changed after this draft was prepared. "
                            "Refresh the queue and prepare a new draft before downloading its list."
                            )
    return Response(supplier_followup.supplier_csv(run, business, group), media_type="text/csv",
                    headers={"Cache-Control": "no-store", "Content-Disposition":
                        f'attachment; filename="supplier-{gstin}-run-{run.id}.csv"'})
