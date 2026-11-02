"""Explicitly requested, read-only AI reviews for the active business."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_business
from app.core.rate_limit import RateLimit
from app.models.business import Business
from app.schemas.action_agent import ReviewOut, ReviewRequest
from app.services import action_agent

router = APIRouter(prefix="/action-agent", tags=["action-agent"])
UNAVAILABLE = (
    "The AI action plan is temporarily unavailable. Your invoices, reconciliation "
    "and filing screens still work. Please try again later."
)


def available() -> None:
    if not settings.openai_api_key.strip() or action_agent.BREAKER.is_open:
        raise HTTPException(status_code=503, detail=UNAVAILABLE)


@router.post(
    "/review", response_model=ReviewOut,
    summary="Review a filing period and prioritise the next actions",
    description=(
        "Read-only review of the active business. Sends aggregate summaries to OpenAI on request; "
        "never changes invoices, contacts suppliers or files returns."
    ),
    responses={503: {"description": "AI review unavailable"}},
    dependencies=[Depends(get_current_business), Depends(available),
                  Depends(RateLimit("action_agent_minute", "3/minute")),
                  Depends(RateLimit("action_agent_daily", "10/day")),
                  Depends(RateLimit("action_agent_site_daily", "200/day", by="site"))],
)
def review_period(
    request: ReviewRequest,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> ReviewOut:
    try:
        # SQLAlchemy is synchronous. Keep both its reads and the bounded
        # provider workflow in FastAPI's worker thread, off the event loop.
        return asyncio.run(action_agent.review(db, business, request))
    except action_agent.AgentUnavailable:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
