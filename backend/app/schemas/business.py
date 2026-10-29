"""Request/response models for the multi-GSTIN business list."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.business import BusinessPlan


class MyBusinessOut(BaseModel):
    """One business this login can act for, and how."""

    id: int
    gstin: str
    legal_name: str
    trade_name: str | None = None
    plan: BusinessPlan
    role: str
    # The caller's own tenant — the one every request acts for when no
    # `X-Business-Id` header is sent — versus one reached through a link.
    is_home: bool


class MyBusinessesOut(BaseModel):
    items: list[MyBusinessOut]


class LinkBusinessIn(BaseModel):
    """The other account's own credentials — proof enough to link it here."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LinkedLoginOut(BaseModel):
    """Another login that has linked this business, and with what role."""

    id: int
    email: str
    role: str
    linked_at: datetime


class LinkedLoginsOut(BaseModel):
    items: list[LinkedLoginOut]
