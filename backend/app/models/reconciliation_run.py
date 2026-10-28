"""Reconciliation runs: one attempt to match a period's books against GSTR-2B."""
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


class ReconciliationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MatchCategory(str, Enum):
    """How one invoice fared against the supplier's filing.

    The five outcomes a reconciliation can reach, and each implies a different
    action: nothing, a call to the supplier, a correction in the books, or a
    provision against ITC that may have to be reversed.
    """

    MATCHED = "matched"  # Same invoice, same figures.
    MISMATCHED = "mismatched"  # Same invoice, different figures.
    MISSING_IN_2B = "missing_in_2b"  # In our books, not in the supplier's GSTR-1.
    MISSING_IN_BOOKS = "missing_in_books"  # In GSTR-2B, not in our books.
    DUPLICATE = "duplicate"  # The same invoice booked more than once.


class ReconciliationRun(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    """A single reconciliation of one period, kept as a record rather than a result.

    Runs accumulate instead of overwriting each other: a period is reconciled
    repeatedly as suppliers file late and the 2B is regenerated, and "what did
    we know, and when" is the question an ITC reversal turns on months later.
    """

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        Index("ix_reconciliation_runs_business_created", "business_id", "created_at"),
        Index("ix_reconciliation_runs_business_period", "business_id", "period"),
        Index(
            "ix_reconciliation_runs_business_period_completed",
            "business_id", "period", "created_at",
            sqlite_where=text("deleted_at IS NULL AND status = 'completed'"),
            postgresql_where=text("deleted_at IS NULL AND status = 'completed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    status: Mapped[ReconciliationStatus] = mapped_column(
        SAEnum(ReconciliationStatus, native_enum=False, length=20),
        default=ReconciliationStatus.RUNNING,
        nullable=False,
    )

    # ---- Counts, one per MatchCategory ----
    total_invoices: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mismatched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_in_2b_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_in_books_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ---- ITC impact ----
    # Credit safe to claim: matched invoices from suppliers who have filed.
    itc_eligible: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    # Credit claimed but resting on an invoice the supplier has not filed. The
    # number that decides whether to hold payment or provide against it.
    itc_at_risk: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)
    itc_claimed: Mapped[Decimal] = mapped_column(MoneyTotal, default=ZERO, nullable=False)

    # Per-invoice findings: ``[{"invoice_id": 1, "category": "mismatched",
    # "field": "igst", "books": "1800.00", "gstr2b": "1620.00"}, ...]``
    report: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ReconciliationRun {self.period} {self.status} matched={self.matched_count}>"
