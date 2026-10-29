"""Email subscribers for GST filing deadline reminders.

Not business-scoped: these are anonymous visitors who have not signed up for
an account. The email is the natural key, and a subscriber who unsubscribes
and resubscribes later gets a fresh ``subscribed_at`` on the same row rather
than a second one.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Subscriber(Base, TimestampMixin):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="landing")
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The last deadline reminder this address was sent, as "GSTR1-2026-09".
    # Written after each successful send, so a second run on the same day — a
    # retry, a restarted worker — sends nobody the same reminder twice, and a
    # failed address is tried again rather than counted as told.
    last_reminded_for: Mapped[str | None] = mapped_column(String(32), nullable=True)
