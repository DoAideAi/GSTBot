"""Request/response models for registration and login."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core import sanitize
from app.core.security import _BCRYPT_MAX_BYTES
from app.models.business import BusinessPlan
from app.models.user import UserRole
from app.services import gstin as gstin_service

# How people write a phone number: an optional leading "+", then digits broken
# up by spaces, hyphens, dots or brackets. Anything else is not a number.
_PHONE_SHAPE = re.compile(r"\+?[0-9(][0-9 ().-]*")
# E.164 allows at most fifteen digits; below seven there is no number anywhere.
_PHONE_DIGITS = (7, 15)

# The handful of passwords that show up at the top of every breach corpus.
# Not a substitute for a real strength check — just a floor.
_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "12345678", "123456789",
        "1234567890", "qwertyuiop", "letmein123", "welcome123", "admin123",
        "iloveyou", "abc12345", "gstbot123", "changeme", "passw0rd",
    }
)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gstin: str | None = None
    legal_name: str
    trade_name: str | None = None
    state_code: str | None = None
    state_name: str = ""
    plan: BusinessPlan
    is_active: bool
    created_at: datetime

    @classmethod
    def from_business(cls, business) -> BusinessOut:
        data = cls.model_validate(business)
        return data.model_copy(
            update={
                "state_name": (
                    gstin_service.STATE_CODES.get(business.state_code, "")
                    if business.state_code
                    else ""
                )
            }
        )


class UserOut(BaseModel):
    """The login itself, independent of which business a request acts for.

    ``role`` here is the role on the login's *own* business, which is not
    necessarily the role it acts with — see :attr:`MeOut.active_role`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
    role: UserRole = Field(
        description=(
            "Role on this login's own business. A request acting for a linked "
            "business through `X-Business-Id` carries a different one."
        )
    )
    is_active: bool
    business_id: int
    created_at: datetime


class MeOut(UserOut):
    """``/auth/me`` — the user plus the tenant they act for.

    Returned together because the frontend needs both on every page load, and
    a second round trip for the business would be one the app always makes.
    """

    business: BusinessOut
    active_role: UserRole = Field(
        description=(
            "The role this login acts with **on `business`** — the one the API "
            "enforces. Gate write controls on this, never on `role`."
        )
    )


class RegisterRequest(BaseModel):
    """Sign-up: create a business and its owner login.

    GSTIN is optional — a user can register to explore the product and add
    their GST registration later. When provided, it is validated, and the
    state code and PAN are decoded from it.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "owner@umangtraders.in",
                "password": "a-long-passphrase",
                "gstin": "27AAPFU0939F1ZV",
                "legal_name": "Umang Traders Private Limited",
                "trade_name": "Umang Traders",
                "full_name": "Umang Shah",
                "phone": "+919820012345",
            }
        }
    )

    email: EmailStr = Field(description="Owner's email. Also the login identifier.")
    password: str = Field(
        min_length=8,
        max_length=128,
        description=(
            "At least 8 characters, and at most 72 bytes of UTF-8: bcrypt reads "
            "no further, so anything longer would protect the account no better. "
            "That is 72 characters in English, about 24 in Hindi."
        ),
    )
    gstin: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "15-character GSTIN of the business, or null to register without one. "
            "Spaces are stripped, case is normalised, and the check digit is verified."
        ),
    )
    legal_name: str | None = Field(
        default=None, max_length=255,
        description="Name as registered with GST. Defaults to full_name or the email local part.",
    )
    trade_name: str | None = Field(
        default=None, max_length=255, description="Name the business trades under."
    )
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("gstin")
    @classmethod
    def _valid_gstin(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        try:
            return gstin_service.parse(v).gstin
        except gstin_service.InvalidGSTIN as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("legal_name", "trade_name", "full_name", "phone")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        # Control characters and bidi overrides are stripped at the edge: these
        # values are rendered in the app, written into a GSTR-1 export and put
        # in a Content-Disposition filename, and none of those want them.
        return sanitize.clean_text(v, max_length=255)

    @field_validator("phone")
    @classmethod
    def _a_phone_number(cls, v: str | None) -> str | None:
        # Runs after ``_clean``, so ``v`` is already trimmed and None if blank.
        # Free text before this: "abc<>" was stored as a phone number, and the
        # column's twenty characters were the only limit on what one could be.
        # Stored as "+" and digits, or digits alone, so one number typed two
        # ways is one number.
        if v is None:
            return None
        digits = re.sub(r"\D", "", v)
        low, high = _PHONE_DIGITS
        if not _PHONE_SHAPE.fullmatch(v) or not low <= len(digits) <= high:
            raise ValueError(
                f"{v!r} is not a phone number. Enter {low} to {high} digits, "
                "optionally starting with + and the country code, e.g. +91 98200 12345."
            )
        return ("+" if v.startswith("+") else "") + digits

    @field_validator("password")
    @classmethod
    def _not_obviously_weak(cls, v: str) -> str:
        # A deliberately shallow check. Real strength enforcement belongs with
        # a breach-corpus check, not a regex; what this catches is the sign-up
        # that would be brute-forced in an afternoon.
        if v.strip() == "":
            raise ValueError(
                "A password cannot be only spaces. Use letters, numbers or symbols."
            )
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("That password is too common. Choose something less guessable.")
        # bcrypt reads the first 72 bytes and ``security._prepare`` cuts there.
        # The 128-character cap let far more through — 128 ASCII characters is
        # 56 bytes past it, and a Devanagari character is 3 bytes — and the
        # rest was silently ignored: a passphrase was only as strong as its
        # first 72 bytes, and any password sharing those opened the account.
        # Refused rather than truncated, so what the user typed is what counts.
        size = len(v.encode("utf-8"))
        if size > _BCRYPT_MAX_BYTES:
            raise ValueError(
                f"That password is {size} bytes long; at most 72 can be used "
                "(72 characters in English, about 24 in Hindi or other Indian "
                "scripts). Choose a shorter one."
            )
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(
        min_length=8,
        max_length=128,
        description=(
            "The same rules as at registration: at least 8 characters, at most 72 "
            "bytes, not a common one."
        ),
    )

    @field_validator("new_password")
    @classmethod
    def _not_obviously_weak(cls, v: str) -> str:
        return RegisterRequest._not_obviously_weak(v)

    @model_validator(mode="after")
    def _a_change(self) -> ChangePasswordRequest:
        if self.new_password == self.current_password:
            raise ValueError("The new password is the same as the current one.")
        return self


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=2048)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _not_obviously_weak(cls, v: str) -> str:
        return RegisterRequest._not_obviously_weak(v)


class RegisterResponse(BaseModel):
    """Registration returns a usable session, not just a created row."""

    user: UserOut
    business: BusinessOut
    access_token: str
    token_type: str = "bearer"
