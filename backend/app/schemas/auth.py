"""Request/response models for registration and login."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core import sanitize
from app.models.business import BusinessPlan
from app.models.user import UserRole
from app.services import gstin as gstin_service

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
            "At least 8 characters. Capped at 128 because bcrypt hashes only the "
            "first 72 bytes, and accepting more would suggest a strength that is "
            "not there."
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
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    """Registration returns a usable session, not just a created row."""

    user: UserOut
    business: BusinessOut
    access_token: str
    token_type: str = "bearer"
