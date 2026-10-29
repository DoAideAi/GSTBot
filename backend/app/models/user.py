"""Login identities, each belonging to exactly one business."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.business import Business


class UserRole(str, Enum):
    OWNER = "owner"
    ACCOUNTANT = "accountant"
    VIEWER = "viewer"


class User(Base, TimestampMixin):
    """A person who signs in.

    Not ``BusinessScopedMixin``: a user's tenant is their identity rather than
    a filter applied to their rows, and the CA Bundle plan will eventually let
    one login reach several businesses through a join table. Keeping the FK
    explicit here leaves room for that without a migration on every other
    table.
    """

    __tablename__ = "users"
    # One account per provider identity. Social sign-in looks a user up by
    # these two columns on every login, and nothing indexed or constrained
    # them: a full scan of users each time, and no guarantee that one Google
    # account could not end up linked to two users. Partial, because a
    # password account has neither.
    __table_args__ = (
        Index(
            "uq_users_oauth_identity",
            "oauth_provider",
            "oauth_id",
            unique=True,
            sqlite_where=text("oauth_id IS NOT NULL"),
            postgresql_where=text("oauth_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=20), default=UserRole.OWNER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # When the password was last changed, to the second. A token issued before
    # it is refused (see ``deps.get_current_user``), so changing a password
    # ends every session the old one opened. ``None``: never changed.
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    referral_code: Mapped[str | None] = mapped_column(
        String(64), index=True, unique=True, nullable=True
    )

    business: Mapped[Business] = relationship(back_populates="users")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"
