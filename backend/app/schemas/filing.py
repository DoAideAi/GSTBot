"""Request/response models for pre-filing validation and portal exports."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import gst_calendar


class ValidationIssueOut(BaseModel):
    """One problem found on one invoice."""

    invoice_id: int | None = None
    invoice_number: str | None = None
    field: str
    # "error" blocks a filing; "warning" does not.
    severity: str
    message: str


class ValidationReportOut(BaseModel):
    """Everything wrong with a period, and whether it can be filed."""

    period: str
    ok: bool
    invoice_count: int
    error_count: int
    warning_count: int
    issues: list[ValidationIssueOut]


class FilingPreviewOut(BaseModel):
    """A generated return, with the validation that ran alongside it.

    The document and its problems travel together on purpose: a GSTR-1 that
    was built from invoices with three invalid GSTINs is not a thing anyone
    should be able to download without being told.
    """

    period: str
    return_type: str
    document: dict
    validation: ValidationReportOut


class RecordFilingIn(BaseModel):
    """What the business tells us after they have filed on the portal."""

    period: str = Field(
        pattern=gst_calendar.PERIOD_PATTERN, description="The period filed, `YYYY-MM`."
    )
    # Optional because the acknowledgement is not always to hand at the moment
    # someone marks a return done, and refusing the record would leave the
    # deadline alert firing for a return that is genuinely filed. It can be
    # supplied later by recording the same period again.
    #
    # Omitting it on that second call leaves any stored reference alone, rather
    # than clearing it — otherwise correcting the date would silently discard
    # the proof of filing.
    arn: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "The portal's Acknowledgement Reference Number, if it is to hand. "
            "Omitting it never clears a reference already recorded."
        ),
    )
    filed_on: date | None = Field(
        default=None,
        description=(
            "Defaults to today in India, where the deadline falls. On a "
            "re-record, omitting it keeps the date already recorded."
        ),
    )

    @field_validator("filed_on")
    @classmethod
    def _filed_on_not_before_gst(cls, v: date | None) -> date | None:
        if v is not None and v < gst_calendar.GST_COMMENCEMENT:
            raise ValueError(
                f"A filing date of {v.isoformat()} predates GST commencement "
                f"({gst_calendar.GST_COMMENCEMENT.isoformat()}). Check the year "
                "on the acknowledgement from the portal."
            )
        return v


class FiledReturnOut(BaseModel):
    """A return this tenant has recorded as filed."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    period: str
    return_type: str
    status: str
    arn: str | None = None
    filed_at: datetime | None = None
    due_date: datetime | None = None
    invoice_count: int
    total_taxable_value: Decimal
    total_cgst: Decimal
    total_sgst: Decimal
    total_igst: Decimal
    total_cess: Decimal
    # True when the recorded filing date is after the statutory due date. The
    # figure a business wants here is not "when did I file" but "was I late",
    # and computing that on the client means shipping the due-date rule twice.
    filed_late: bool = False


class FilingStatusItemOut(BaseModel):
    """One period and one return type: due when, filed or not."""

    period: str
    return_type: str
    due_date: date
    filed: bool
    filed_on: date | None = None
    arn: str | None = None
    filed_late: bool = False
    # Negative once the due date has passed.
    days_until_due: int


class FilingStatusOut(BaseModel):
    """Recent periods and where each return stands."""

    as_of: date
    items: list[FilingStatusItemOut]


class LateFeeOut(BaseModel):
    """What ss.47 and 50 cost one return, as of one date.

    ``projected`` is true while the return sits unfiled: the figures are a
    running estimate that grows by the day rather than a settled amount.
    """

    period: str
    return_type: str
    due_date: date
    as_of: date
    filed_on: date | None = None
    days_late: int
    projected: bool
    is_nil: bool
    net_tax_liability: Decimal
    late_fee_cgst: Decimal
    late_fee_sgst: Decimal
    late_fee_total: Decimal
    late_fee_tier: str
    interest: Decimal
    total_payable: Decimal
