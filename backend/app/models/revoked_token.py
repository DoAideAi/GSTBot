"""Access tokens signed out before they expired."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RevokedToken(Base):
    """One signed-out token, by its ``jti``, kept only until it would expire.

    Logout used to be the browser forgetting its copy, so a token copied before
    sign-out stayed good for its full lifetime. One token, not the user: an
    owner and their CA on one login, or a phone and a laptop, sign out of one
    session without ending the other. A row is worthless once ``expires_at``
    passes — the token is refused for being expired anyway — and the logout
    route prunes those, so the table holds at most a day of sign-outs.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
