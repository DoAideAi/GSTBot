"""Every Razorpay payment applied to a subscription, once."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class SubscriptionPayment(Base, TimestampMixin):
    """A verified payment and the period it bought.

    The subscription row holds only the *latest* payment, so it could not say
    whether a payment had been applied before: re-verifying an older one —
    a genuine order, genuinely paid, signature intact — read as a new purchase
    and added another period. One row per payment, unique across tenants
    because a payment belongs to one checkout, is what lets verify-payment
    answer a payment it has already seen without applying it twice.

    Billing rather than tenant data, like ``subscriptions``: not soft-deleted,
    since a payment that has been applied stays applied, and its payment id is
    unique across tenants on purpose — so it declares ``business_id`` itself
    rather than taking ``BusinessScopedMixin``'s tenant-data rules.
    """

    __tablename__ = "subscription_payments"
    __table_args__ = (
        Index("ix_subscription_payments_business_created", "business_id", "created_at"),
        # verify-payment's one-order-one-period check (migration 0024).
        Index("ix_subscription_payments_order", "razorpay_order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SubscriptionPayment business_id={self.business_id} {self.razorpay_payment_id}>"
