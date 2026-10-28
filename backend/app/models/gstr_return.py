"""GSTR return periods: what was filed, what was fetched, what is still a draft."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import (
    ZERO,
    BusinessScopedMixin,
    JSONType,
    MoneyTotal,
    SoftDeleteMixin,
    TimestampMixin,
)


class ReturnType(str, Enum):
    GSTR1 = "gstr1"  # Outward supplies we declare.
    GSTR2B = "gstr2b"  # Static ITC statement the portal generates for us.
    GSTR3B = "gstr3b"  # Monthly summary and payment.


class ReturnStatus(str, Enum):
    DRAFT = "draft"  # Generated from our data, not submitted.
    READY = "ready"  # Validated and exportable.
    FILED = "filed"  # Acknowledged by the portal.
    IMPORTED = "imported"  # Pulled from the portal (the normal state of a 2B).


class GSTRReturn(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    """One return, for one period, of one type.

    ``data`` holds the portal-shaped JSON — the GSTR-1 ``b2b``/``b2cs`` blocks,
    or the ``docdata`` of a GSTR-2B — rather than a normalised form of it. The
    portal's schema is the interoperability contract and it changes on the
    government's timetable, so the raw document is what gets stored and the
    summary columns beside it are what the product reads day to day.
    """

    __tablename__ = "gstr_returns"
    __table_args__ = (
        # One live return per period and type — but only among the undeleted.
        # The portal regenerates a GSTR-2B whenever a supplier files late, so
        # re-importing a period is routine, and the superseded import is
        # soft-deleted rather than dropped. A plain unique constraint would
        # count those tombstones and make the second import fail.
        Index(
            "uq_gstr_returns_business_period_type",
            "business_id",
            "period",
            "return_type",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_gstr_returns_business_created", "business_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # ``YYYY-MM``. A string rather than a date because a GST period is a month,
    # and "2026-04-01" invites a reader to think a day means something here.
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    return_type: Mapped[ReturnType] = mapped_column(
        SAEnum(ReturnType, native_enum=False, length=10), nullable=False
    )
    status: Mapped[ReturnStatus] = mapped_column(
        SAEnum(ReturnStatus, native_enum=False, length=10),
        default=ReturnStatus.DRAFT,
        nullable=False,
    )

    data: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    # ---- Summary, denormalised for the dashboard ----
    invoice_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_taxable_value: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    total_cgst: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    total_sgst: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    total_igst: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    total_cess: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)

    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Validation problems found before filing (missing GSTIN, HSN mismatch,
    # impossible tax rate). Surfaced to the user; never a reason to drop a row.
    validation_errors: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<GSTRReturn {self.return_type} {self.period} {self.status}>"
