"""Schemas for public endpoints that live outside the domain routers."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, EmailStr, Field


class ReminderSubscribeRequest(BaseModel):
    email: EmailStr


class SubscriberRequest(BaseModel):
    email: EmailStr
    # Which page's form it came from: an attribution label, so its shape is
    # checked rather than its value. It was an allow-list of four while the
    # tool pages each send their own — "eway-bill", "itc-mismatch", forty-odd
    # more — so 42 of the site's 46 reminder forms answered every sign-up with
    # a 422 and stored nothing. A lowercase slug that fits the column (50);
    # test_subscribers reads every source off the frontend and sends it here.
    source: str = Field(
        default="landing",
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
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
