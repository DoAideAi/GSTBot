"""Product feedback from the floating widget.

Not business-scoped: anyone can send it, signed in or not, and the people who
read it are the operators of the site rather than any one tenant. The email is
optional and only for a reply, so it is not a key and is not unique.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FeedbackCategory(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    GENERAL = "general"
    OTHER = "other"


class Feedback(Base):
    __tablename__ = "feedback"
    # The admin list reads newest first, optionally narrowed to one category.
    __table_args__ = (Index("ix_feedback_category_created", "category", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[FeedbackCategory] = mapped_column(
        SAEnum(
            FeedbackCategory,
            name="feedback_category",
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=20,
        ),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
