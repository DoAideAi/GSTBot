"""One-time introductory access, separate from payment records."""
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class PilotEnrollment(Base, TimestampMixin):
    __tablename__ = "pilot_enrollments"
    __table_args__ = (
        UniqueConstraint("tier", "cohort_slot", name="uq_pilot_cohort_slot"),
        CheckConstraint(
            "(tier = 'pro' AND cohort_slot BETWEEN 1 AND 20) OR "
            "(tier = 'enterprise' AND cohort_slot BETWEEN 1 AND 10)", name="ck_pilot_capacity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    tier: Mapped[str] = mapped_column(String(20))
    cohort_slot: Mapped[int] = mapped_column()
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def active(self, now: datetime | None = None) -> bool:
        start = self.starts_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        end = self.ends_at.replace(tzinfo=UTC) if self.ends_at.tzinfo is None else self.ends_at
        return start <= (now or datetime.now(UTC)) < end


class PilotBusiness(Base, TimestampMixin):
    __tablename__ = "pilot_businesses"
    __table_args__ = (
        UniqueConstraint("pilot_id", "slot", name="uq_pilot_business_slot"),
        CheckConstraint("slot BETWEEN 1 AND 5", name="ck_pilot_business_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pilot_id: Mapped[int] = mapped_column(ForeignKey("pilot_enrollments.id"), index=True)
    # Keep history after expiry: a business cannot be recycled into another
    # cohort, and its existing reports remain downloadable.
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), unique=True)
    slot: Mapped[int] = mapped_column()
