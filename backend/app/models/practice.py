"""Durable import previews, invitations and accountant review evidence."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import BusinessScopedMixin, JSONType, SoftDeleteMixin, TimestampMixin


class RegisterImport(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "register_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mapping: Mapped[dict] = mapped_column(JSONType, nullable=False)
    headers: Mapped[list] = mapped_column(JSONType, nullable=False)
    rows: Mapped[list] = mapped_column(JSONType, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONType)


class RegisterMapping(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "register_mappings"
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_register_mapping_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    mapping: Mapped[dict] = mapped_column(JSONType, nullable=False)
    date_format: Mapped[str] = mapped_column(String(10), nullable=False)


class BusinessInvitation(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "business_invitations"
    __table_args__ = (
        UniqueConstraint("business_id", "token_hash", name="uq_business_invitation_token"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FindingReview(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "finding_reviews"
    __table_args__ = (
        UniqueConstraint("business_id", "run_id", "finding_index", name="uq_finding_review"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    finding_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    decision: Mapped[str] = mapped_column(String(30), default="none", nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class FindingReviewEvent(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "finding_review_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("finding_reviews.id"), nullable=False, index=True
    )
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    previous: Mapped[dict | None] = mapped_column(JSONType)
    current: Mapped[dict] = mapped_column(JSONType, nullable=False)


class ReportReview(Base, BusinessScopedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "report_reviews"
    __table_args__ = (UniqueConstraint("business_id", "run_id", name="uq_report_review"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False)
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


for _model in (
    RegisterImport,
    RegisterMapping,
    BusinessInvitation,
    FindingReview,
    FindingReviewEvent,
    ReportReview,
):
    Index(f"ix_{_model.__tablename__}_business_created", _model.business_id, _model.created_at)
