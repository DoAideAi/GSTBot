"""Product feedback: posted by anyone from the widget, read by site admins."""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, date, datetime, time
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.core.params import Offset, RowId
from app.core.rate_limit import RateLimit, client_ip
from app.models.feedback import ClientError, Feedback, FeedbackCategory
from app.models.mixins import utcnow
from app.schemas.feedback import (
    ClientErrorAck,
    ClientErrorCreate,
    ClientErrorListOut,
    ClientErrorOut,
    FeedbackCreate,
    FeedbackListOut,
    FeedbackOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Five an hour per address: enough for someone who has several things to say,
# few enough that the inbox cannot be flooded from one connection.
_submit_limit = RateLimit("feedback", "5/hour", by="ip")
_read_limit = RateLimit("feedback_read", "120/minute")
# Error reports are sent by the browser on its own, so a visitor never sees
# this refused: the widget sends each distinct error once per page load. It is
# here because the endpoint is public and every *new* message is a new row —
# without a ceiling, one script could fill the table.
_error_limit = RateLimit("client_error", "30/minute", by="ip")

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
        meta=body.metadata.model_dump(exclude_none=True) if body.metadata else None,
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


def _bare_page(page: str) -> str:
    """The page without its query string or fragment.

    Both for the fingerprint — ``/lookup?gstin=A`` and ``/lookup?gstin=B``
    failing the same way is one error — and because a query or fragment can
    carry a sign-in code or reset token that has no business being stored.
    """
    try:
        parts = urlsplit(page)
    except ValueError:
        return page.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@router.post(
    "/error",
    summary="Report an uncaught browser error",
    description=(
        "Public — sent by the frontend on its own when a page throws. The same "
        "message on the same page is stored once and counted, so `occurrences` "
        "in the answer says how many times it has been seen."
    ),
    response_model=ClientErrorAck,
    responses={
        422: {"description": "The page or message is missing, or a field is too long."},
        429: {"description": "More than thirty reports from this address in a minute."},
    },
    dependencies=[Depends(_error_limit)],
)
def report_client_error(
    body: ClientErrorCreate, request: Request, db: Session = Depends(get_db)
) -> ClientErrorAck:
    page = _bare_page(body.page)
    fingerprint = hashlib.sha256(f"{page}\n{body.message}".encode()).hexdigest()

    def bump() -> int | None:
        db.execute(
            update(ClientError)
            .where(ClientError.fingerprint == fingerprint)
            .values(occurrences=ClientError.occurrences + 1, last_seen_at=utcnow())
        )
        db.commit()
        return db.scalar(
            select(ClientError.occurrences).where(ClientError.fingerprint == fingerprint)
        )

    seen = db.scalar(select(ClientError.id).where(ClientError.fingerprint == fingerprint))
    if seen is not None:
        return ClientErrorAck(occurrences=bump() or 1)

    db.add(
        ClientError(
            fingerprint=fingerprint,
            page=page,
            message=body.message,
            stack=body.stack,
            user_agent=(request.headers.get("user-agent") or "")[:MAX_USER_AGENT] or None,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Two tabs reported the same crash at once and the other one won the
        # insert: that is a second occurrence, not a failure.
        db.rollback()
        return ClientErrorAck(occurrences=bump() or 1)
    logger.info("Client error recorded", extra={"page": page})
    return ClientErrorAck(occurrences=1)


# ---------------------------------------------------------------------------
# Admin housekeeping: read the error log, clear what has been dealt with
# ---------------------------------------------------------------------------

_ADMIN = [Depends(_read_limit), Depends(require_admin)]
_ADMIN_REFUSALS = {
    401: {"description": "Not signed in."},
    403: {"description": "Signed in, but not a site administrator."},
}


@router.get(
    "/errors",
    summary="List uncaught browser errors (admins only)",
    description=(
        "One row per (page, message), most recently seen first, with how many "
        "times it has happened. Restricted to `ADMIN_EMAILS`."
    ),
    response_model=ClientErrorListOut,
    responses=_ADMIN_REFUSALS,
    dependencies=_ADMIN,
)
def list_client_errors(
    limit: int = Query(default=50, ge=1, le=200),
    offset: Offset = 0,
    db: Session = Depends(get_db),
) -> ClientErrorListOut:
    total = db.scalar(select(func.count()).select_from(ClientError)) or 0
    rows = db.scalars(
        select(ClientError)
        .order_by(ClientError.last_seen_at.desc(), ClientError.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ClientErrorListOut(items=[ClientErrorOut.model_validate(r) for r in rows], total=total)


@router.delete(
    "/errors/{error_id}",
    summary="Clear a browser error once it is fixed (admins only)",
    description=(
        "Removes the row. If the error happens again it is recorded afresh, "
        "with its count starting from one — which is how a regression shows."
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ADMIN_REFUSALS, 404: {"description": "No such error."}},
    dependencies=_ADMIN,
)
def delete_client_error(error_id: RowId, db: Session = Depends(get_db)) -> Response:
    row = db.get(ClientError, error_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That error is not in the log."
        )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{feedback_id}",
    summary="Delete one piece of feedback (admins only)",
    description="For spam and test submissions. Restricted to `ADMIN_EMAILS`.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ADMIN_REFUSALS, 404: {"description": "No such feedback."}},
    dependencies=_ADMIN,
)
def delete_feedback(feedback_id: RowId, db: Session = Depends(get_db)) -> Response:
    row = db.get(Feedback, feedback_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That feedback is not here."
        )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
