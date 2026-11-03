"""Tenant-safe review state and the facts behind a firm's client queue."""

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models.business import Business
from app.models.business_membership import BusinessMembership
from app.models.invoice import Invoice
from app.models.practice import FindingReview, ReportReview
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.models.user import User
from app.services import reconciliation
from app.services.register_import import aware


def scoped_run(db, business_id, run_id, lock=False):
    query = select(ReconciliationRun).where(
        ReconciliationRun.id == run_id,
        ReconciliationRun.business_id == business_id,
        ReconciliationRun.deleted_at.is_(None),
    )
    run = db.scalar(query.with_for_update() if lock else query)
    if run is None:
        raise HTTPException(404, "Reconciliation run not found for this business.")
    if run.status != ReconciliationStatus.COMPLETED:
        raise HTTPException(409, "Wait for a completed reconciliation before reviewing it.")
    return run


def reviewer_options(db, business_id):
    linked = select(BusinessMembership.user_id).where(
        BusinessMembership.business_id == business_id,
        BusinessMembership.deleted_at.is_(None),
        BusinessMembership.role.in_(["OWNER", "ACCOUNTANT"]),
    )
    # Enums store member names in SQL; the home-user branch uses the same names.
    users = db.scalars(
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                (User.business_id == business_id) & User.role.in_(["OWNER", "ACCOUNTANT"]),
                User.id.in_(linked),
            ),
        )
        .order_by(User.full_name, User.id)
    )
    return [{"id": u.id, "name": u.full_name or u.email} for u in users]


def review_out(review):
    return {
        "id": review.id,
        "finding_index": review.finding_index,
        "status": review.status,
        "decision": review.decision,
        "assignee_id": review.assignee_id,
        "note": review.note,
        "version": review.version,
        "updated_by": review.updated_by,
        "updated_at": review.updated_at.isoformat() if review.updated_at else None,
    }


def is_stale(db, business_id, run):
    latest = reconciliation.latest_completed_run(db, business_id, run.period, with_report=False)
    if latest is None or latest.id != run.id or run.completed_at is None:
        return True
    stamp = aware(run.completed_at)
    # Deletions and edits can change both the period and the identity of a
    # source row. Include tombstones and carried invoice ids in this check.
    source_ids = [
        f["invoice_id"] for f in (run.report or {}).get("findings", []) if f.get("invoice_id")
    ]
    changed = db.scalar(
        select(func.max(Invoice.updated_at)).where(
            Invoice.business_id == business_id,
            or_(Invoice.period == run.period, Invoice.id.in_(source_ids)),
        )
    )
    statement = reconciliation.latest_gstr2b(db, business_id, run.period)
    return bool(
        (changed and aware(changed) > stamp) or (statement and aware(statement.updated_at) > stamp)
    )


def review_summary(db, run):
    rows = list(
        db.scalars(
            select(FindingReview).where(
                FindingReview.business_id == run.business_id,
                FindingReview.deleted_at.is_(None),
                FindingReview.run_id == run.id,
            )
        )
    )
    by_index = {r.finding_index: r for r in rows}
    findings = (run.report or {}).get("findings", [])
    unresolved = sum(
        (f.get("category") != "matched" or i in by_index)
        and (i not in by_index or by_index[i].status != "resolved"
             or by_index[i].decision != "accept_match")
        for i, f in enumerate(findings)
    )
    approval = db.scalar(
        select(ReportReview).where(
            ReportReview.business_id == run.business_id,
            ReportReview.deleted_at.is_(None),
            ReportReview.run_id == run.id,
        )
    )
    return rows, unresolved, approval


def accessible_businesses(db, user):
    linked = select(BusinessMembership.business_id).where(
        BusinessMembership.user_id == user.id, BusinessMembership.deleted_at.is_(None)
    )
    return select(Business).where(
        Business.reachable(), or_(Business.id == user.business_id, Business.id.in_(linked))
    )
