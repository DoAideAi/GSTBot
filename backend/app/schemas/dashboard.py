"""Response models for the dashboard."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class TaxBucket(BaseModel):
    """Totals for one direction of trade."""

    count: int = 0
    taxable_value: Decimal = Decimal("0.00")
    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    cess: Decimal = Decimal("0.00")
    total_tax: Decimal = Decimal("0.00")
    total_value: Decimal = Decimal("0.00")


class InvoiceCounts(BaseModel):
    total: int = 0
    sales: int = 0
    purchase: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    # Parsed but low-confidence or warning-carrying: the review queue.
    needs_review: int = 0


class PlanUsage(BaseModel):
    plan: str
    invoices_this_month: int
    monthly_limit: int = Field(description="0 means unlimited")
    remaining: int | None = Field(default=None, description="null when unlimited")


class NetLiability(BaseModel):
    """Output tax minus input credit, per head.

    The three heads are kept apart because GST does not let them be pooled:
    IGST credit can be set against IGST, then CGST, then SGST, but CGST credit
    can never discharge an SGST liability. A single netted figure would read
    as cash the business does not have.
    """

    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    cess: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")


class PeriodSummary(BaseModel):
    period: str
    sales: TaxBucket
    purchase: TaxBucket
    credit: TaxBucket = Field(
        default_factory=TaxBucket,
        description=(
            "The claimable part of `purchase`: tax on purchases whose credit is "
            "neither blocked under s.17(5) nor under reverse charge. This is "
            "what `net_liability` is computed against."
        ),
    )
    net_liability: NetLiability


class DashboardOut(BaseModel):
    business_gstin: str | None = None
    business_name: str
    period: str
    counts: InvoiceCounts
    sales: TaxBucket
    purchase: TaxBucket
    credit: TaxBucket = Field(
        default_factory=TaxBucket,
        description=(
            "The claimable part of `purchase`: tax on purchases whose credit is "
            "neither blocked under s.17(5) nor under reverse charge. Reported "
            "beside `purchase` so a business can see why the two differ."
        ),
    )
    net_liability: NetLiability
    # Output tax owed on sales for the period, before credit is applied: the
    # ``output`` bucket, not ``sales`` — a reverse-charge sale's tax is the
    # recipient's to pay.
    output_tax: Decimal = Decimal("0.00")
    # Input credit available from purchases for the period. The claimable part
    # only — this is `credit.total_tax`, not `purchase.total_tax`.
    input_tax_credit: Decimal = Decimal("0.00")
    itc_at_risk: Decimal = Decimal("0.00")
    plan_usage: PlanUsage
    recent_periods: list[PeriodSummary] = Field(default_factory=list)
    open_alerts: int = 0
    next_due_date: date | None = None
    gstr1_due_date: date | None = None
    last_reconciliation: dict | None = None
    # Only set once the GSTR-3B for `period` is actually overdue and still
    # unfiled — see app.services.late_fee. A period that is on time, or
    # already recorded filed, has nothing running on it to show here.
    late_fee_estimate: dict | None = None
