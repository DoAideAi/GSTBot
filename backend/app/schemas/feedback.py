"""Schemas for the feedback widget and the admin inbox."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.feedback import FeedbackCategory

MAX_MESSAGE = 5000
MAX_PAGE_URL = 2048
DAY_MS = 86_400_000

Path = Annotated[str, Field(max_length=300)]
Note = Annotated[str, Field(max_length=300)]


class FeedbackMetadata(BaseModel):
    """What the widget observed about the visit, attached to a submission.

    Every field is optional and bounded, and unknown keys are dropped rather
    than refused: a newer widget sending a field this server does not know yet
    must not cost the visitor their feedback.
    """

    model_config = ConfigDict(extra="ignore")

    pages: list[Path] | None = Field(default=None, max_length=50)
    feature_area: str | None = Field(default=None, max_length=60)
    time_on_page_ms: int | None = Field(default=None, ge=0, le=DAY_MS)
    session_ms: int | None = Field(default=None, ge=0, le=DAY_MS)
    scroll_depth_pct: int | None = Field(default=None, ge=0, le=100)
    click_count: int | None = Field(default=None, ge=0, le=1_000_000)
    rage_clicks: int | None = Field(default=None, ge=0, le=1_000_000)
    rage_click_targets: list[Note] | None = Field(default=None, max_length=10)
    form_abandoned: bool | None = None
    form_time_ms: int | None = Field(default=None, ge=0, le=DAY_MS)
    js_errors: int | None = Field(default=None, ge=0, le=1_000_000)
    js_error_messages: list[Note] | None = Field(default=None, max_length=5)
    reloaded: bool | None = None
    viewport: str | None = Field(default=None, max_length=20)


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FeedbackCategory = FeedbackCategory.GENERAL
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE)
    email: EmailStr | None = None
    page_url: str | None = Field(default=None, max_length=MAX_PAGE_URL)
    metadata: FeedbackMetadata | None = None

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
    # Read from the model's `meta`: `metadata` on a Declarative class is the
    # table registry, not this column.
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="meta")
    created_at: datetime


class FeedbackListOut(BaseModel):
    items: list[FeedbackOut]
    total: int


class ClientErrorCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: str = Field(..., min_length=1, max_length=MAX_PAGE_URL)
    message: str = Field(..., min_length=1, max_length=2000)
    stack: str | None = Field(default=None, max_length=10_000)


class ClientErrorAck(BaseModel):
    occurrences: int


class ClientErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page: str
    message: str
    stack: str | None
    user_agent: str | None
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime


class ClientErrorListOut(BaseModel):
    items: list[ClientErrorOut]
    total: int
