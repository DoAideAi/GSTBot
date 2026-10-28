"""Column types and mixins shared by every model.

Two things live here because getting them wrong is expensive everywhere:

* **Money.** GST is computed to the paisa and reported to the rupee, and a
  float cannot hold ``18%`` of ``₹1,234.56`` exactly. Every monetary column is
  ``Numeric(16, 2)``, which SQLAlchemy hands back as ``Decimal``.
* **Tenancy and soft delete.** The feature doc requires ``business_id`` on
  every business-owned table and soft delete only. Both are mixins so a new
  table gets them by inheriting rather than by remembering.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.types import JSON

# JSONB on Postgres (indexable, typed) and plain JSON on SQLite (tests).
JSONType = JSON().with_variant(JSONB, "postgresql")

# Money: 16 digits with 2 decimals. Comfortably holds a crore-scale invoice
# line without ever rounding through a float.
Money = Numeric(16, 2)

# The largest figure those columns can hold: fourteen digits before the point.
# Declared beside the type so the two cannot drift, and exported because a
# bound on the column alone is enforced in two different places by the two
# databases this runs on — Postgres refuses the INSERT, SQLite keeps whatever
# it was handed — and neither of those is where a caller should find out.
#
# It is also a bound on the *arithmetic*. ``Decimal.quantize`` raises
# ``InvalidOperation`` rather than rounding once the result needs more than the
# context's 28 significant digits, and every figure in this product is
# quantized to the paisa on its way out. A single amount past that limit
# therefore does not merely store wrongly: it makes every screen that totals it
# raise, which is a 500 on a read caused by a write that answered 200.
MONEY_MAX = Decimal("99999999999999.99")

# A period's total of Money figures. ``MONEY_MAX`` bounds one invoice, not the
# sum of a month of them: three invoices each just inside it made a filing's
# or a reconciliation's stored total wider than ``Money`` holds, which
# Postgres refuses with ``numeric field overflow`` — a 500 on "mark filed"
# and a failed run, reached only through figures every field accepted. Six
# more digits hold a million invoices at the ceiling, past what even the
# unlimited plans upload in a month.
MoneyTotal = Numeric(22, 2)

ZERO = Decimal("0.00")


def utcnow() -> datetime:
    """Timezone-aware now, for defaults set in Python rather than by the DB."""
    return datetime.now(UTC)


class TimestampMixin:
    """``created_at`` / ``updated_at``, maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """``deleted_at``, set instead of issuing a DELETE.

    Business data is never hard-deleted: a GST filing can be reopened years
    later during an assessment, and a row that is gone cannot be explained to
    an officer. Queries filter on ``deleted_at.is_(None)``.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = utcnow()


class BusinessScopedMixin:
    """A non-null ``business_id`` FK plus an index on it.

    Declared here rather than per-model so that "multi-tenant from day 1" is
    structural: a table that inherits this cannot be written without a tenant,
    and every tenant-filtered query has an index to use.

    The composite ``(business_id, created_at)`` index that every scoped table
    also needs is *not* declared here. It was, via ``declared_attr.directive``,
    and it never once took effect: all five scoped models declare their own
    ``__table_args__`` for a unique constraint or a second composite index, and
    a class attribute shadows an inherited ``declared_attr`` completely — there
    is no merge. Each model therefore had to spell the index out anyway, and
    the mixin's copy only made it look like it was inherited. Deleting it
    changes no DDL; ``test_model_registry.py`` is what actually holds the line,
    by failing when a scoped table is missing the index.
    """

    @declared_attr
    def business_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
        )
