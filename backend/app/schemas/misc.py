"""Schemas for public endpoints that live outside the domain routers."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, EmailStr, Field


class ReminderSubscribeRequest(BaseModel):
    email: EmailStr


class SubscriberRequest(BaseModel):
    email: EmailStr
    source: str = Field(
        default="landing",
        pattern=r"^(calculator|lookup|filing-dates|landing)$",
    )


class BulkGstinRequest(BaseModel):
    # Each entry bounded too: an invalid one is echoed back in its result, so
    # without a cap a request could have up to a hundred strings of any length
    # parsed and returned. 64 is the GPT lookup's bound for the same value.
    gstins: list[Annotated[str, Field(max_length=64)]] = Field(..., min_length=1, max_length=100)


class BulkGstinResult(BaseModel):
    gstin: str
    valid: bool
    error: str | None = None
    state_code: str | None = None
    state_name: str | None = None
    pan: str | None = None


class BulkGstinResponse(BaseModel):
    results: list[BulkGstinResult]
    total: int
    valid_count: int
    invalid_count: int


class FeedbackRequest(BaseModel):
    page: str = Field(..., max_length=500)
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(default="", max_length=2000)
    timestamp: str = Field(..., max_length=40)
