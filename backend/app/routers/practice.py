"""Accountant review queue and a portfolio of explicitly accessible clients."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, get_current_user, require_writer
from app.core.params import RowId
from app.core.rate_limit import RateLimit
from app.core.sanitize import clean_text
from app.models.business import Business
from app.models.invoice import Invoice, InvoiceType
from app.models.mixins import utcnow
from app.models.practice import FindingReview, FindingReviewEvent, ReportReview
from app.models.user import User
from app.routers.reconciliation import _pilot_report, _purchase_for
from app.schemas.practice import ClientQueueOut, FindingReviewUpdate
from app.services import gst_calendar, practice, reconciliation, review_workbook

router = APIRouter(prefix="/practice", tags=["CA workspace"])


@router.get(
    "/clients",
    response_model=ClientQueueOut,
    summary="Next reconciliation task for each accessible client",
    dependencies=[Depends(RateLimit("practice_clients", "60/minute"))],
)
def clients(
    period: str = Query(pattern=gst_calendar.PERIOD_PATTERN),
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    query = practice.accessible_businesses(db, user)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    businesses = db.scalars(query.order_by(Business.id).offset(offset).limit(limit))
    items = []
    for business in businesses:
        purchase_count = (
            db.scalar(
                select(func.count(Invoice.id)).where(
                    Invoice.business_id == business.id,
                    Invoice.invoice_type == InvoiceType.PURCHASE,
                    Invoice.period == period,
                    Invoice.deleted_at.is_(None),
                )
            )
            or 0
        )
        statement = reconciliation.latest_gstr2b(db, business.id, period)
        run = reconciliation.latest_completed_run(db, business.id, period)
        _, pending, approval = practice.review_summary(db, run) if run else ([], None, None)
        stale = practice.is_stale(db, business.id, run) if run else False
        ready = bool(approval and approval.invalidated_at is None and not stale)
        items.append(
            {
                "id": business.id,
                "name": business.trade_name or business.legal_name,
                "gstin": business.gstin,
                "purchase_count": purchase_count,
                "has_2b": statement is not None,
                "run_id": run.id if run else None,
                "unresolved": pending,
                "stale": stale,
                "reviewed": ready,
                "exported": bool(ready and approval.exported_at),
                "next_action": (
                    "Import purchases"
                    if not purchase_count
                    else (
                        "Import GSTR-2B"
                        if not statement
                        else (
                            "Run reconciliation"
                            if not run or stale
                            else (
                                "Review exceptions"
                                if pending
                                else (
                                    "Review report"
                                    if not ready
                                    else (
                                        "Export reviewed report"
                                        if not approval.exported_at
                                        else "Period reviewed and exported"
                                    )
                                )
                            )
                        )
                    )
                ),
            }
        )
    return {"items": items, "period": period, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/runs/{run_id}",
    summary="Review findings and their recorded history",
    dependencies=[Depends(RateLimit("practice_read", "120/minute"))],
)
def workbench(
    run_id: RowId, db: Session = Depends(get_db), business: Business = Depends(get_current_business)
) -> dict:
    run = practice.scoped_run(db, business.id, run_id)
    reviews, unresolved, approval = practice.review_summary(db, run)
    events = db.scalars(
        select(FindingReviewEvent)
        .where(
            FindingReviewEvent.business_id == business.id,
            FindingReviewEvent.deleted_at.is_(None),
            FindingReviewEvent.review_id.in_([r.id for r in reviews]),
        )
        .order_by(FindingReviewEvent.id.desc())
        .limit(200)
    )
    return {
        "run_id": run.id,
        "period": run.period,
        "findings": (run.report or {}).get("findings", []),
        "reviews": [practice.review_out(r) for r in reviews],
        "unresolved": unresolved,
        "stale": practice.is_stale(db, business.id, run),
        "reviewers": practice.reviewer_options(db, business.id),
        "approved": bool(approval and approval.invalidated_at is None),
        "exported_at": approval.exported_at if approval else None,
        "events": [
            {
                "id": e.id,
                "review_id": e.review_id,
                "actor_id": e.actor_id,
                "at": e.created_at,
                "previous": e.previous,
                "current": e.current,
            }
            for e in events
        ],
    }


@router.patch(
    "/runs/{run_id}/findings/{finding_index}",
    summary="Record a versioned accountant decision",
    dependencies=[Depends(require_writer), Depends(RateLimit("practice_review", "60/minute"))],
)
def review_finding(
    run_id: RowId,
    payload: FindingReviewUpdate,
    finding_index: int = Path(ge=0, le=100000),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
    user: User = Depends(get_current_user),
) -> dict:
    run = practice.scoped_run(db, business.id, run_id, lock=True)
    findings = (run.report or {}).get("findings", [])
    if finding_index >= len(findings):
        raise HTTPException(404, "This finding does not exist in the selected run.")
    if practice.is_stale(db, business.id, run):
        raise HTTPException(
            409,
            "Source data or the latest run changed. Reconcile again "
            "before recording a current review.",
        )
    if payload.assignee_id is not None and payload.assignee_id not in {
        r["id"] for r in practice.reviewer_options(db, business.id)
    }:
        raise HTTPException(
            422, "Assign this finding to an active owner or accountant for this business."
        )
    note = clean_text(payload.note, max_length=2000) or ""
    if payload.status == "resolved" and (not note or payload.decision != "accept_match"):
        raise HTTPException(
            422,
            "Confirm the recorded finding with an evidence note to resolve it. "
            "If you disagree, correct the source and reconcile again.",
        )
    review = db.scalar(
        select(FindingReview).where(
            FindingReview.business_id == business.id,
            FindingReview.deleted_at.is_(None),
            FindingReview.run_id == run.id,
            FindingReview.finding_index == finding_index,
        )
    )
    if payload.version != (review.version if review else 0):
        raise HTTPException(
            409, "Another reviewer changed this finding. Reload before saving your decision."
        )
    previous = practice.review_out(review) if review else None
    if review is None:
        review = FindingReview(
            business_id=business.id,
            run_id=run.id,
            finding_index=finding_index,
            updated_by=user.id,
            version=0,
        )
        db.add(review)
    review.status, review.decision = payload.status, payload.decision
    review.assignee_id, review.note = payload.assignee_id, note
    review.updated_by, review.version = user.id, review.version + 1
    db.flush()
    db.add(
        FindingReviewEvent(
            business_id=business.id,
            review_id=review.id,
            actor_id=user.id,
            previous=previous,
            current=practice.review_out(review),
        )
    )
    approval = db.scalar(
        select(ReportReview).where(
            ReportReview.run_id == run.id,
            ReportReview.business_id == business.id,
            ReportReview.deleted_at.is_(None),
        )
    )
    if approval:
        approval.invalidated_at = utcnow()
    db.commit()
    return practice.review_out(review)


@router.post(
    "/runs/{run_id}/approve",
    summary="Confirm the complete reconciliation report was reviewed",
    dependencies=[Depends(require_writer), Depends(RateLimit("practice_approve", "30/minute"))],
)
def approve_report(
    run_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
    user: User = Depends(get_current_user),
) -> dict:
    run = practice.scoped_run(db, business.id, run_id, lock=True)
    _, unresolved, approval = practice.review_summary(db, run)
    if unresolved or practice.is_stale(db, business.id, run):
        raise HTTPException(
            409,
            "Resolve outstanding findings and reconcile any changed "
            "source data before completing review.",
        )
    if approval is None:
        approval = ReportReview(
            business_id=business.id, run_id=run.id, reviewed_by=user.id, reviewed_at=utcnow()
        )
        db.add(approval)
    approval.reviewed_by, approval.reviewed_at = user.id, utcnow()
    approval.invalidated_at, approval.exported_at = None, None
    db.commit()
    return {"reviewed": True, "reviewed_at": approval.reviewed_at}


def safe_cell(value):
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get(
    "/runs/{run_id}/export.csv",
    summary="Export an entitled reviewed report as CSV",
    dependencies=[Depends(RateLimit("practice_export", "30/minute"))],
    response_class=Response,
)
def export_review(
    run_id: RowId, db: Session = Depends(get_db), business: Business = Depends(get_current_business)
) -> Response:
    run, reviews, approval = reviewed_export(db, business, run_id)
    return csv_export(db, run, reviews, approval)


def reviewed_export(db, business, run_id):
    run = practice.scoped_run(db, business.id, run_id, lock=True)
    if not _pilot_report(db, business.id, run) and _purchase_for(db, business.id, run.id) is None:
        raise HTTPException(
            402,
            "This export uses the same access as the reconciliation PDF. "
            "Start an eligible pilot or buy this run’s report from "
            "Reconcile.",
        )
    reviews, unresolved, approval = practice.review_summary(db, run)
    if (
        not approval
        or approval.invalidated_at
        or unresolved
        or practice.is_stale(db, business.id, run)
    ):
        raise HTTPException(
            409, "Complete review of the current run before exporting the reviewed report."
        )
    return run, reviews, approval


def csv_export(db, run, reviews, approval):
    by_index = {r.finding_index: r for r in reviews}
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "Run",
            "Period",
            "Invoice",
            "Supplier GSTIN",
            "Original match result",
            "Books tax",
            "2B tax",
            "Review status",
            "Review decision",
            "Reviewer note",
        ]
    )
    for i, finding in enumerate((run.report or {}).get("findings", [])):
        review = by_index.get(i)
        writer.writerow(
            [
                safe_cell(v)
                for v in [
                    run.id,
                    run.period,
                    finding.get("invoice_number"),
                    finding.get("supplier_gstin"),
                    finding.get("category"),
                    (finding.get("books") or {}).get("total_tax"),
                    (finding.get("gstr2b") or {}).get("total_tax"),
                    review.status if review else "report_reviewed",
                    review.decision if review else "none",
                    review.note if review else "Reviewed as part of the report",
                ]
            ]
        )
    approval.exported_at = utcnow()
    db.commit()
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="reviewed-reconciliation-{run.id}.csv"'
        },
    )


@router.get(
    "/runs/{run_id}/export.xlsx",
    summary="Export an entitled reviewed report as an Excel workbook",
    dependencies=[Depends(RateLimit("practice_workbook", "10/minute"))],
    response_class=Response,
)
def export_workbook(
    run_id: RowId, db: Session = Depends(get_db), business: Business = Depends(get_current_business)
) -> Response:
    run, reviews, approval = reviewed_export(db, business, run_id)
    events = db.scalars(select(FindingReviewEvent).where(
        FindingReviewEvent.business_id == business.id,
        FindingReviewEvent.deleted_at.is_(None),
        FindingReviewEvent.review_id.in_([r.id for r in reviews]),
    ).order_by(FindingReviewEvent.id))
    content = review_workbook.build(run, business, reviews, approval, events)
    approval.exported_at = utcnow()
    db.commit()
    return Response(content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Cache-Control": "no-store", "Content-Disposition":
                 f'attachment; filename="reviewed-reconciliation-{run.id}.xlsx"'})
