"""Usage tracking: count API calls per business per month, enforce tier limits."""
from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.subscription import Subscription, SubscriptionTier
from app.models.usage import UsageRecord
from app.services.invoice_service import month_of

logger = logging.getLogger(__name__)

# Monthly limits per tier.  0 = unlimited.
TIER_LIMITS: dict[SubscriptionTier, dict[str, int]] = {
    SubscriptionTier.FREE: {
        "gst_lookup": 5,
        "hsn_search": 0,
        "bulk_operation": 0,
        "api_access": 0,
    },
    SubscriptionTier.PRO: {
        "gst_lookup": 0,
        "hsn_search": 0,
        "bulk_operation": 0,
        "api_access": 0,
    },
    SubscriptionTier.ENTERPRISE: {
        "gst_lookup": 0,
        "hsn_search": 0,
        "bulk_operation": 0,
        "api_access": 0,
    },
}


def current_period() -> str:
    """``YYYY-MM`` for the current month in India.

    It was the UTC month, while the invoice allowance this page now shows
    beside these counters is counted by the Indian one (``month_of``): from
    00:00 to 05:30 IST on the 1st the two named different months.
    """
    return month_of()


def get_subscription(db: Session, business_id: int) -> Subscription | None:
    return db.scalar(
        select(Subscription).where(Subscription.business_id == business_id)
    )


def get_tier(db: Session, business_id: int) -> SubscriptionTier:
    sub = get_subscription(db, business_id)
    if sub is None or not sub.is_paid():
        # Covers a lapsed period as well as a cancelled row: once the paid
        # period ends, the business is on the free tier's limits.
        return SubscriptionTier.FREE
    return sub.tier


def record_usage(
    db: Session, business_id: int, endpoint: str, count: int = 1
) -> UsageRecord:
    """Increment the usage counter for a (business, period, endpoint) triple.

    An increment in the database, not read-modify-write: two requests in the
    same month would otherwise both read the count and one increment would be
    lost, and two *first* requests would both insert and the second would hit
    the unique key. The insert runs in a savepoint so losing that race costs
    only the savepoint, and the loser increments the row the winner made.
    """
    period = current_period()
    where = (
        UsageRecord.business_id == business_id,
        UsageRecord.period == period,
        UsageRecord.endpoint == endpoint,
    )
    bump = update(UsageRecord).where(*where).values(call_count=UsageRecord.call_count + count)
    if db.execute(bump).rowcount == 0:
        try:
            with db.begin_nested():
                db.add(
                    UsageRecord(
                        business_id=business_id,
                        period=period,
                        endpoint=endpoint,
                        call_count=count,
                    )
                )
        except IntegrityError:
            db.execute(bump)
    db.flush()
    return db.scalar(select(UsageRecord).where(*where))


def check_limit(
    db: Session, business_id: int, endpoint: str
) -> tuple[bool, int, int]:
    """``(allowed, used, limit)`` — whether the business may make this call.

    ``limit=0`` means unlimited.
    """
    tier = get_tier(db, business_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS[SubscriptionTier.FREE])
    limit = limits.get(endpoint, 0)
    if limit == 0:
        return True, 0, 0

    period = current_period()
    row = db.scalar(
        select(UsageRecord).where(
            UsageRecord.business_id == business_id,
            UsageRecord.period == period,
            UsageRecord.endpoint == endpoint,
        )
    )
    used = row.call_count if row else 0
    allowed = used < limit
    if not allowed:
        logger.warning(
            "Usage limit reached",
            extra={
                "business_id": business_id,
                "endpoint": endpoint,
                "used": used,
                "limit": limit,
                "tier": tier.value,
                "period": period,
            },
        )
    return allowed, used, limit


def get_usage_summary(
    db: Session, business_id: int, period: str | None = None
) -> list[dict]:
    """All usage rows for a business in a period, as dicts."""
    period = period or current_period()
    rows = db.scalars(
        select(UsageRecord)
        .where(
            UsageRecord.business_id == business_id,
            UsageRecord.period == period,
        )
        .order_by(UsageRecord.endpoint)
    ).all()
    tier = get_tier(db, business_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS[SubscriptionTier.FREE])
    return [
        {
            "endpoint": r.endpoint,
            "call_count": r.call_count,
            "limit": limits.get(r.endpoint, 0),
            "period": r.period,
        }
        for r in rows
    ]
