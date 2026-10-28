"""Everything this product holds about one business, as one JSON document.

What a business may ask for under the DPDP Act's right of access, and what it
needs to leave: the filing exports cover a period's returns, the API pages
through one list at a time, and nothing produced the whole account.

Driven by the mapper registry rather than a list of tables. Every mapped table
with a ``business_id`` column contributes its rows for this business — today
the invoices, suppliers, runs, returns, alerts, purchases, subscription,
payments, usage, memberships and the business's own logins — so a table added
next year is in the export the day it ships, and ``test_data_export`` fails if
one is ever left out. Soft-deleted rows are included and say so in their
``deleted_at``: the data is still held, so it is still theirs to see.

Only what is not the business's data, or is not safe to hand back, is left
out — see :data:`WITHHELD`.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  -- registers every model on Base.metadata
from app.core.database import Base
from app.models.business import Business

FORMAT_VERSION = 1

# (table, column) pairs that never leave the server. A password hash is a
# credential, not data about anyone; an OAuth subject id is the provider's
# handle for the person, useful only for signing in as them; a storage path is
# where this server keeps a file, which says nothing to the business and
# something to an attacker.
WITHHELD = frozenset(
    {
        ("users", "hashed_password"),
        ("users", "oauth_id"),
        ("invoices", "storage_path"),
    }
)


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        # A string, as the API sends money: a float would round it.
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(db: Session, table, business_id: int) -> list[dict[str, Any]]:
    columns = [c for c in table.columns if (table.name, c.name) not in WITHHELD]
    order = [table.c.id] if "id" in table.c else []
    result = db.execute(
        select(*columns).where(table.c.business_id == business_id).order_by(*order)
    )
    return [{key: _value(value) for key, value in row._mapping.items()} for row in result]


def exported_tables() -> list:
    """Every table holding rows that belong to one business, by name."""
    return sorted(
        (t for t in Base.metadata.sorted_tables if "business_id" in t.c),
        key=lambda t: t.name,
    )


def export_business(db: Session, business: Business, *, exported_at: datetime) -> dict[str, Any]:
    """The whole account of *business*."""
    own = Base.metadata.tables[Business.__tablename__]
    profile = db.execute(
        select(*[c for c in own.columns if (own.name, c.name) not in WITHHELD]).where(
            own.c.id == business.id
        )
    ).one()
    return {
        "format_version": FORMAT_VERSION,
        "exported_at": exported_at.isoformat(),
        "business": {key: _value(value) for key, value in profile._mapping.items()},
        "tables": {t.name: _rows(db, t, business.id) for t in exported_tables()},
        "withheld": sorted(f"{table}.{column}" for table, column in WITHHELD),
    }
