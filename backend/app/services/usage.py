"""Usage tracking: count API calls per business per month, enforce tier limits."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.subscription import Subscription, SubscriptionTier
from app.models.usage import UsageRecord

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
    """``YYYY-MM`` for the current UTC month."""
    return datetime.now(UTC).strftime("%Y-%m")


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
    """Increment the usage counter for a (business, period, endpoint) triple."""
    period = current_period()
    row = db.scalar(
        select(UsageRecord).where(
            UsageRecord.business_id == business_id,
            UsageRecord.period == period,
            UsageRecord.endpoint == endpoint,
        )
    )
    if row is None:
        row = UsageRecord(
            business_id=business_id,
            period=period,
            endpoint=endpoint,
            call_count=count,
        )
        db.add(row)
    else:
        row.call_count += count
    db.flush()
    return row


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
