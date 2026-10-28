"""Reading the alerts the sweep raises, and closing the ones you have handled.

The daily sweep in ``app/services/alerting.py`` writes rows and the dashboard
counts them. Until this router there was nothing in between: no way to read what
an alert said, and — more to the point — no way to dismiss one. The sweep's
central rule is that a dismissal is respected and never raised again, and that
rule could not fire, because no caller could produce a dismissal.

**Two verbs, not a status field.** ``PATCH {"status": ...}`` would be the shorter
API and the wrong one. Of the six statuses only two belong to the business —
read it, or close it. PENDING, SENT and FAILED are delivery state that a future
sender owns, and RESOLVED means the return was actually filed. A client that
could write RESOLVED would destroy the one measurement the enum split exists
for: whether these alerts cause anybody to do anything.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, require_writer
from app.core.params import Offset, RowId
from app.core.rate_limit import RateLimit
from app.models.alert import (
    OPEN_STATUSES,
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from app.models.business import Business
from app.schemas.alert import AlertListOut, AlertOut, AlertScope
from app.services import gst_calendar

router = APIRouter(prefix="/alerts", tags=["alerts"])

_read_limit = RateLimit("alert_read", "240/minute")
# Reading and dismissing are one click each, and a client that clears a
# backlog does it one row at a time.
_write_limit = RateLimit("alert_write", "120/minute")

# Loudest first. The enum's own values sort "critical, info, warning"
# alphabetically, which is nearly the reverse of what a to-do list wants, so
# the rank is spelled out rather than left to the column.
_SEVERITY_RANK = case(
    (Alert.severity == AlertSeverity.CRITICAL, 0),
    (Alert.severity == AlertSeverity.WARNING, 1),
    else_=2,
)

# Dated alerts before undated ones, soonest first. Expressed as a flag column
# rather than NULLS LAST because that clause is a dialect difference between
# the Postgres this deploys on and the SQLite the suite runs, and an ordering
# that silently differs between the two is the kind of thing a test cannot see.
_UNDATED_LAST = case((Alert.due_date.is_(None), 1), else_=0)


def _move_if(
    db: Session, alert: Alert, to: AlertStatus, *, only_from: tuple[AlertStatus, ...]
) -> Alert:
    """Set *alert*'s status to *to* only if it is still in *only_from*.

    Pinned in the WHERE rather than decided off the loaded row, because the
    daily sweep writes the same column: an alert loaded open and resolved by the
    sweep before this commits would otherwise be overwritten — a filed return's
    RESOLVED turned into DISMISSED, the one difference the alert history exists
    to keep. Same guard ``alert_delivery`` puts on its SENT/FAILED stamp.
    """
    db.execute(
        update(Alert)
        .where(Alert.id == alert.id, Alert.status.in_(only_from))
        .values(status=to)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(alert)
    return alert


def _owned_alert(db: Session, business: Business, alert_id: int) -> Alert:
    """Fetch an alert, 404ing on anything outside the caller's tenant.

    404 rather than 403 for another tenant's row, as everywhere else here: a
    403 confirms the id exists.
    """
    alert = db.scalar(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.business_id == business.id,
            Alert.deleted_at.is_(None),
        )
    )
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found. Refresh the alerts list and try again.",
        )
    return alert


@router.get(
    "",
    response_model=AlertListOut,
    summary="What this business still has to act on",
    description=(
        "Open alerts by default — everything that has not been dismissed and "
        "has not been resolved by the thing it asked for actually happening. "
        "Pass `scope=closed` for the ones that are done with, or `scope=all`.\n\n"
        "Ordered by how much it matters rather than by when it arrived: "
        "critical first, then by due date soonest-first, then newest. An "
        "overdue GSTR-3B outranks a reminder about a return due next week even "
        "if the reminder was raised this morning.\n\n"
        "`open_total` counts every outstanding alert for the business, not the "
        "ones on this page — it is the same number the dashboard badge shows, "
        "so a client filtering to one type still knows the whole picture."
    ),
    dependencies=[Depends(_read_limit)],
)
def list_alerts(
    scope: AlertScope = Query(
        default=AlertScope.OPEN,
        description="`open` (the default), `closed`, or `all`.",
    ),
    alert_type: AlertType | None = Query(
        default=None,
        alias="type",
        description="Restrict to one kind, e.g. `filing_deadline`.",
    ),
    severity: AlertSeverity | None = Query(
        default=None, description="Restrict to `info`, `warning` or `critical`."
    ),
    period: str | None = Query(
        default=None,
        pattern=gst_calendar.PERIOD_PATTERN,
        description="Filing period as `YYYY-MM`, for alerts that are about one.",
        examples=["2026-04"],
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size, 1-200."),
    offset: Offset = 0,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> AlertListOut:
    """What this business still has to act on, most serious first."""
    scoped = [Alert.business_id == business.id, Alert.deleted_at.is_(None)]
    conditions = list(scoped)

    if scope is AlertScope.OPEN:
        conditions.append(Alert.status.in_(OPEN_STATUSES))
    elif scope is AlertScope.CLOSED:
        conditions.append(Alert.status.not_in(OPEN_STATUSES))
    if alert_type:
        conditions.append(Alert.alert_type == alert_type)
    if severity:
        conditions.append(Alert.severity == severity)
    if period:
        conditions.append(Alert.period == period)

    total = int(db.scalar(select(func.count(Alert.id)).where(*conditions)) or 0)
    open_total = int(
        db.scalar(
            select(func.count(Alert.id)).where(
                *scoped, Alert.status.in_(OPEN_STATUSES)
            )
        )
        or 0
    )
    rows = db.scalars(
        select(Alert)
        .where(*conditions)
        .order_by(
            _SEVERITY_RANK,
            _UNDATED_LAST,
            Alert.due_date,
            Alert.created_at.desc(),
            Alert.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()

    return AlertListOut(
        items=[AlertOut.model_validate(row) for row in rows],
        total=total,
        open_total=open_total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{alert_id}/read",
    response_model=AlertOut,
    summary="Mark an alert as seen",
    description=(
        "Seen, not handled. The alert stays open and keeps counting towards "
        "the badge, because a filing deadline someone has looked at is exactly "
        "as unmet as one they have not — `dismiss` is what says otherwise.\n\n"
        "Idempotent, and it never reopens anything: an alert that was already "
        "dismissed, or that the sweep resolved because the return got filed, "
        "comes back unchanged."
    ),
    responses={404: {"description": "No such alert in this tenant."}},
    dependencies=[Depends(_write_limit), Depends(require_writer)],
)
def mark_read(
    alert_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> AlertOut:
    """Mark an alert as seen, without closing it."""
    alert = _owned_alert(db, business, alert_id)
    if alert.status in OPEN_STATUSES and alert.status is not AlertStatus.READ:
        unread = tuple(s for s in OPEN_STATUSES if s is not AlertStatus.READ)
        alert = _move_if(db, alert, AlertStatus.READ, only_from=unread)
    return AlertOut.model_validate(alert)


@router.post(
    "/{alert_id}/dismiss",
    response_model=AlertOut,
    summary="Close an alert: the business knows",
    description=(
        "The daily sweep respects this. A dismissed filing-deadline alert is "
        "not raised again tomorrow, which is the whole reason this endpoint "
        "exists — an alert that reappears every morning is one that gets the "
        "notifications turned off.\n\n"
        "It is not permanent. If the situation genuinely gets worse — the "
        "deadline passing, say — the sweep raises the alert again with the new "
        "severity, because that is new information rather than the same "
        "reminder.\n\n"
        "An alert that was already resolved stays resolved: it closed because "
        "the return was filed, and recording that as a dismissal instead would "
        "lose the difference between an alert that worked and one that was "
        "swatted away."
    ),
    responses={404: {"description": "No such alert in this tenant."}},
    dependencies=[Depends(_write_limit), Depends(require_writer)],
)
def dismiss(
    alert_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> AlertOut:
    """Close an alert. The sweep will not raise it again unless it worsens."""
    alert = _owned_alert(db, business, alert_id)
    if alert.status in OPEN_STATUSES:
        alert = _move_if(db, alert, AlertStatus.DISMISSED, only_from=tuple(OPEN_STATUSES))
    return AlertOut.model_validate(alert)
