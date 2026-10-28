"""Request models for the public GPT Actions API (``/api/v1/gpt``).

Every string carries a length or a pattern and every amount a floor and a
ceiling, for the reasons the route-contract sweeps give: these are public, and
a field with no bound is one whose contents a 422 quotes back in full.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.mixins import MONEY_MAX

STATE_CODE_PATTERN = r"^\d{2}$"
HSN_PATTERN = r"^\d{4,8}$"

# A GSTIN is 15 characters; the slack is for the spaces and hyphens people
# paste out of PDFs, which ``gstin.normalize`` strips. Same ceiling as the
# public lookup in ``routers/misc.py``.
GSTIN_INPUT_MAX = 64

# Bounds on one invoice line. A quantity of a million and a hundred lines are
# both far past any invoice a person dictates into a chat; what they bound is
# the work one anonymous request can ask for.
QUANTITY_MAX = Decimal("1000000")
MAX_LINES = 100


def _has_words(value: str) -> str:
    """Trimmed, and refused if nothing is left.

    ``min_length=1`` counts spaces, so a party called "   " or an item described
    as "   " passed and came back on a tax invoice with that box blank.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must contain something other than spaces")
    return stripped


class InvoiceParty(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    _name_has_words = field_validator("name")(_has_words)
    gstin: str | None = Field(default=None, max_length=GSTIN_INPUT_MAX)
    state_code: str | None = Field(
        default=None, pattern=STATE_CODE_PATTERN,
        description="Two-digit GST state code. Not needed when a GSTIN is given.",
    )
    address: str | None = Field(default=None, max_length=500)


class InvoiceItem(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    _description_has_words = field_validator("description")(_has_words)
    hsn_code: str | None = Field(default=None, pattern=HSN_PATTERN)
    quantity: Decimal = Field(gt=0, le=QUANTITY_MAX)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: Decimal = Field(ge=0, le=MONEY_MAX, description="Price per unit, before GST.")
    gst_rate: Decimal = Field(ge=0, le=40, description="GST rate in percent, e.g. 18.")
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class InvoiceRequest(BaseModel):
    seller: InvoiceParty
    buyer: InvoiceParty
    items: list[InvoiceItem] = Field(min_length=1, max_length=MAX_LINES)
    invoice_number: str | None = Field(default=None, max_length=50)
    invoice_date: date | None = None
    place_of_supply: str | None = Field(
        default=None, pattern=STATE_CODE_PATTERN,
        description="State code where the supply is delivered. Defaults to the buyer's state.",
    )
    round_off: bool = Field(default=True, description="Round the grand total to the nearest rupee.")
    notes: str | None = Field(default=None, max_length=1000)
