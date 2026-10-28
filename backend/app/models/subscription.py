"""Subscriptions: Razorpay-backed recurring billing per business."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"
    EXPIRED = "expired"


PAID_TIERS = frozenset({SubscriptionTier.PRO, SubscriptionTier.ENTERPRISE})

# How long one payment buys. Fixed day counts rather than calendar months, so
# the end is the same instant whatever day the payment lands on.
PERIOD_DAYS = {"monthly": 30, "annual": 365}


def period_length(billing: str) -> timedelta:
    return timedelta(days=PERIOD_DAYS[billing])


class Subscription(Base, TimestampMixin):
    """A business's active subscription, tracked against Razorpay.

    One row per business.  The ``razorpay_subscription_id`` is null for
    businesses on the free tier — they have no payment relationship.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tier: Mapped[SubscriptionTier] = mapped_column(
        SAEnum(SubscriptionTier, native_enum=False, length=20),
        default=SubscriptionTier.FREE,
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, native_enum=False, length=20),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    razorpay_subscription_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )
    razorpay_customer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    razorpay_plan_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # When the paid period this row was bought for ends. Checkout is a one-time
    # Razorpay order at the monthly or annual price — there is no Razorpay
    # subscription behind it to send ``subscription.expired`` — so without this
    # a single monthly payment bought PRO forever. Null for rows that predate
    # it and for grants made by hand, which stay honoured as before.
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def lapsed(self, now: datetime | None = None) -> bool:
        """Whether the paid period has ended. A row with no end has not."""
        end = self.current_period_end
        if end is None:
            return False
        if end.tzinfo is None:  # SQLite hands back naive UTC
            end = end.replace(tzinfo=UTC)
        return end <= (now or datetime.now(UTC))

    def is_paid(self, now: datetime | None = None) -> bool:
        """An active paid tier whose period has not run out."""
        return (
            self.tier in PAID_TIERS
            and self.status == SubscriptionStatus.ACTIVE
            and not self.lapsed(now)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Subscription business_id={self.business_id} tier={self.tier.value}>"
