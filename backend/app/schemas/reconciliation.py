"""Request/response models for GSTR-2B import and reconciliation."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.params import MAX_ID, MIN_ID
from app.models.gstr_return import ReturnStatus, ReturnType
from app.models.reconciliation_run import ReconciliationStatus
from app.services import gst_calendar


class GSTR2BImportOut(BaseModel):
    """What an import returns: enough to confirm the right file went in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    return_type: ReturnType
    status: ReturnStatus
    invoice_count: int
    total_taxable_value: Decimal
    total_cgst: Decimal
    total_sgst: Decimal
    total_igst: Decimal
    total_cess: Decimal
    created_at: datetime

    # Periods found inside the file that are not the period it was filed under.
    # A 2B routinely carries late-filed invoices from earlier months, and those
    # reconcile against *their* period, not this statement's.
    other_periods: list[str] = Field(default_factory=list)
    replaced_previous: bool = False
    # The upload was the statement already on file: nothing was stored or
    # replaced, and the route answers 200 rather than 201.
    unchanged: bool = False
    # Documents in sections of the statement this import does not read —
    # bills of entry, ISD credit, e-commerce operator supplies — by section.
    # Their credit is in the portal's 2B but not in the totals above.
    unread_sections: dict[str, int] = Field(default_factory=dict)
    message: str = ""


class ReconciliationRunOut(BaseModel):
    """A run's headline figures, without the per-invoice report."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    status: ReconciliationStatus
    total_invoices: int
    matched_count: int
    mismatched_count: int
    missing_in_2b_count: int
    missing_in_books_count: int
    duplicate_count: int
    itc_eligible: Decimal
    itc_at_risk: Decimal
    itc_claimed: Decimal
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    created_at: datetime


class ReconciliationDetailOut(ReconciliationRunOut):
    """A run with its findings — what the reconciliation screen renders."""

    report: dict | None = None


class ImportedPeriodsOut(BaseModel):
    """Periods with a GSTR-2B on file, newest first.

    An envelope like every other list in the API. It was the one bare JSON
    array, which can never gain a field — a count, a cursor — without breaking
    every client that reads it.
    """

    items: list[str]


class ReconciliationListOut(BaseModel):
    items: list[ReconciliationRunOut]
    total: int
    limit: int
    offset: int


class ReconcileRequest(BaseModel):
    """Ask for a period to be reconciled."""

    period: str = Field(pattern=gst_calendar.PERIOD_PATTERN)
    # Rupee gap treated as agreement. Exposed because a business reconciling
    # high-value inter-state invoices may reasonably accept a wider band than
    # the default, and because a CA checking a specific dispute wants to set it
    # to zero and see everything.
    tolerance: Decimal = Field(default=Decimal("1.00"), ge=0, le=1000)


class ReportOrderRequest(BaseModel):
    """Which run's PDF report to buy."""

    # Bounded at both ends like every path id (``app.core.params``): a body
    # id is looked up the same way, and one wider than the column raised
    # ``OverflowError`` out of the driver — a 500 from a JSON field.
    run_id: int = Field(ge=MIN_ID, le=MAX_ID)


class ReportOrderOut(BaseModel):
    """A Razorpay order for one report, or word that it is already paid for.

    ``already_purchased`` short-circuits checkout: a report this business has
    paid for is downloaded again, never charged for twice, and the order fields
    are null because no order was created.
    """

    run_id: int
    already_purchased: bool
    order_id: str | None = None
    amount: int | None = None
    currency: str | None = None
    # The publishable key id Checkout needs in the browser. The key secret
    # never leaves the server.
    razorpay_key_id: str | None = None


class ReportVerifyRequest(BaseModel):
    """What Razorpay Checkout hands the browser after a successful payment."""

    run_id: int = Field(ge=MIN_ID, le=MAX_ID)
    # Shaped like Razorpay's ids. The order id is put into the path of a
    # request made with this server's credentials (``fetch_order``), so a
    # "/" or "." in it could aim that request at another Razorpay endpoint.
    razorpay_order_id: str = Field(max_length=64, pattern=r"^order_[A-Za-z0-9_]+$")
    razorpay_payment_id: str = Field(max_length=64, pattern=r"^pay_[A-Za-z0-9_]+$")
    razorpay_signature: str = Field(max_length=512)


class ReportPurchaseOut(BaseModel):
    """A verified purchase, and where the report is fetched from."""

    run_id: int
    purchased: bool
    download_path: str
