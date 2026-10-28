"""Request/response models for subscription and payment endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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
    created_at: datetime
    updated_at: datetime


class UsageItem(BaseModel):
    endpoint: str
    call_count: int
    limit: int
    period: str


class UsageSummaryResponse(BaseModel):
    tier: SubscriptionTier
    period: str
    usage: list[UsageItem]
