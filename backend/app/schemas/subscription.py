"""Request/response models for subscription and payment endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.subscription import SubscriptionStatus, SubscriptionTier


class TierFeatures(BaseModel):
    name: str
    price_monthly: int
    price_annual: int = 0
    price_display: str
    features: list[str]


class PricingResponse(BaseModel):
    tiers: dict[str, TierFeatures]
    razorpay_key_id: str


class CreateOrderRequest(BaseModel):
    tier: SubscriptionTier
    billing: str = Field(default="monthly", pattern=r"^(monthly|annual)$")


class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    razorpay_key_id: str
    tier: SubscriptionTier


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = Field(max_length=64)
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=512)
    tier: SubscriptionTier


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    tier: SubscriptionTier
    status: SubscriptionStatus
    # When the paid period ends; null for a row sold without one.
    current_period_end: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _a_lapsed_period_reads_as_expired(self) -> SubscriptionOut:
        """An active row whose period has run out is not active.

        The row's status is only moved by Razorpay webhooks, and one-time
        checkout orders produce none, so the stored status stays ``active``
        after the end. Reported as ``expired`` so the app stops presenting a
        plan the business no longer has.
        """
        end = self.current_period_end
        if end is not None and self.status == SubscriptionStatus.ACTIVE:
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            if end <= datetime.now(UTC):
                self.status = SubscriptionStatus.EXPIRED
        return self


class UsageItem(BaseModel):
    endpoint: str
    call_count: int
    limit: int
    period: str


class UsageSummaryResponse(BaseModel):
    tier: SubscriptionTier
    period: str
    usage: list[UsageItem]
