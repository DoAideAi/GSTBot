"""One paid PDF report of one reconciliation run."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import BusinessScopedMixin, SoftDeleteMixin, TimestampMixin


class ReportPurchase(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    """A verified Razorpay payment for a run's PDF report.

    Written only once the payment is verified, so a row *is* the entitlement:
    the download route asks whether one exists for the run and nothing else.
    Bought per run rather than per period, because a period is re-run as
    suppliers file late and each run is a different report.

    Uniqueness leads with ``business_id`` like every scoped table's, and that
    loses nothing here: an order's receipt names the business and run it was
    created for and verification refuses any other, so another tenant's
    payment can never reach this table under this tenant. Not predicated on
    ``deleted_at IS NULL`` either, unlike the rest — a payment that has been
    redeemed once stays redeemed, whatever later happens to the row.
    """

    __tablename__ = "report_purchases"
    __table_args__ = (
        Index("ix_report_purchases_business_created", "business_id", "created_at"),
        UniqueConstraint(
            "business_id", "razorpay_order_id", name="uq_report_purchases_business_order"
        ),
        UniqueConstraint(
            "business_id", "razorpay_payment_id", name="uq_report_purchases_business_payment"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ReportPurchase business_id={self.business_id} run_id={self.run_id}>"
