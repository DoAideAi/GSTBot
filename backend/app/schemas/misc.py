"""Schemas for public endpoints that live outside the domain routers."""
from __future__ import annotations

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
    gstins: list[str] = Field(..., min_length=1, max_length=100)


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
