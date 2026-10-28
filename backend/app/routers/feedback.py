"""Product feedback: posted by anyone from the widget, read by site admins."""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.params import Offset
from app.core.rate_limit import RateLimit, client_ip
from app.models.feedback import Feedback, FeedbackCategory
from app.schemas.feedback import FeedbackCreate, FeedbackListOut, FeedbackOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Five an hour per address: enough for someone who has several things to say,
# few enough that the inbox cannot be flooded from one connection.
_submit_limit = RateLimit("feedback", "5/hour", by="ip")
_read_limit = RateLimit("feedback_read", "120/minute")

MAX_USER_AGENT = 512


@router.post(
    "",
    summary="Send product feedback",
    description=(
        "Public — no sign-in. Called from the floating feedback widget on every "
        "page. The user agent and the caller's address are recorded server-side; "
        "the client supplies only what the visitor typed and the page they were on."
    ),
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackOut,
    responses={
        422: {"description": "The message is missing or blank, or a field is malformed."},
        429: {"description": "More than five submissions from this address in an hour."},
    },
    dependencies=[Depends(_submit_limit)],
)
def submit_feedback(
    body: FeedbackCreate, request: Request, db: Session = Depends(get_db)
) -> Feedback:
    row = Feedback(
        category=body.category,
        message=body.message,
        email=str(body.email) if body.email else None,
        page_url=body.page_url,
        user_agent=(request.headers.get("user-agent") or "")[:MAX_USER_AGENT] or None,
        ip_address=client_ip(request),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Feedback received", extra={"category": row.category.value})
    return row


@router.get(
    "",
    summary="List feedback (admins only)",
    description=(
        "Newest first. `category` narrows to one kind; `since` and `until` are "
        "inclusive calendar dates in UTC. Restricted to the sign-in emails in "
        "`ADMIN_EMAILS`, because each row can carry a visitor's email and address."
    ),
    response_model=FeedbackListOut,
    responses={
        401: {"description": "Not signed in."},
        403: {"description": "Signed in, but not a site administrator."},
        422: {"description": "`since` is after `until`, or a parameter is malformed."},
    },
    dependencies=[Depends(_read_limit), Depends(require_admin)],
)
def list_feedback(
    category: FeedbackCategory | None = Query(default=None),
    since: date | None = Query(default=None, description="First day to include (UTC)."),
    until: date | None = Query(default=None, description="Last day to include (UTC)."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: Offset = 0,
    db: Session = Depends(get_db),
) -> FeedbackListOut:
    if since and until and since > until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The start date must be on or before the end date.",
        )
    filters = []
    if category is not None:
        filters.append(Feedback.category == category)
    if since is not None:
        filters.append(Feedback.created_at >= datetime.combine(since, time.min, UTC))
    if until is not None:
        # End of that day rather than the start of the next: `until + 1 day`
        # overflows on 9999-12-31 and would answer a 500.
        filters.append(Feedback.created_at <= datetime.combine(until, time.max, UTC))

    total = db.scalar(select(func.count()).select_from(Feedback).where(*filters)) or 0
    rows = db.scalars(
        select(Feedback)
        .where(*filters)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return FeedbackListOut(
        items=[FeedbackOut.model_validate(r) for r in rows], total=total
    )
