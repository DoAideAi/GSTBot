"""Schemas for the feedback widget and the admin inbox."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.feedback import FeedbackCategory

MAX_MESSAGE = 5000
MAX_PAGE_URL = 2048


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FeedbackCategory = FeedbackCategory.GENERAL
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE)
    email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=MAX_PAGE_URL)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Feedback cannot be blank.")
        return stripped

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email_is_none(cls, value: object) -> object:
        # The widget's email box is optional; an untouched one sends "".
        return None if isinstance(value, str) and not value.strip() else value


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: FeedbackCategory
    message: str
    email: str | None
    page_url: str | None
    user_agent: str | None
    ip_address: str | None
    created_at: datetime


class FeedbackListOut(BaseModel):
    items: list[FeedbackOut]
    total: int
