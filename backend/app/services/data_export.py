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

import json
from collections.abc import Iterator
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

# Rows fetched from the database per round trip, and serialised per chunk sent.
# The export used to be assembled whole — every invoice with its OCR text and
# extraction, every GSTR-2B ever imported (superseded ones are kept, at up to
# 15 MB each) — and then rendered into a second copy as one JSON string, all
# inside an API worker on a box shared with a dozen other services. Streamed,
# it holds one batch at a time however large the account. Fifty rather than a
# round few hundred because a row can carry tens of kilobytes of OCR text, and
# a batch is held twice — fetched, and serialised.
_BATCH_ROWS = 50

# Separators match what JSONResponse renders, so the file is byte-for-byte the
# shape it was.
_dumps = json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).encode

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


def _rows(db: Session, table, business_id: int) -> Iterator[dict[str, Any]]:
    """*table*'s rows for *business_id*, read in batches rather than all at once.

    ``yield_per`` with ``stream_results``: on Postgres a server-side cursor, so
    the driver does not buffer the whole result either.
    """
    columns = [c for c in table.columns if (table.name, c.name) not in WITHHELD]
    order = [table.c.id] if "id" in table.c else []
    result = db.execute(
        select(*columns)
        .where(table.c.business_id == business_id)
        .order_by(*order)
        .execution_options(stream_results=True, yield_per=_BATCH_ROWS)
    )
    for row in result:
        yield {key: _value(value) for key, value in row._mapping.items()}


def exported_tables() -> list:
    """Every table holding rows that belong to one business, by name."""
    return sorted(
        (t for t in Base.metadata.sorted_tables if "business_id" in t.c),
        key=lambda t: t.name,
    )


def iter_export(
    db: Session,
    business: Business,
    *,
    exported_at: datetime,
    counts: dict[str, int] | None = None,
) -> Iterator[str]:
    """The whole account of *business*, as JSON text in pieces.

    Concatenated, the pieces are the document :func:`export_business` returns.
    *counts*, when given, is filled with each table's row count as it is
    written — known only once the last piece has been produced.
    """
    own = Base.metadata.tables[Business.__tablename__]
    profile = db.execute(
        select(*[c for c in own.columns if (own.name, c.name) not in WITHHELD]).where(
            own.c.id == business.id
        )
    ).one()
    yield (
        '{"format_version":' + _dumps(FORMAT_VERSION)
        + ',"exported_at":' + _dumps(exported_at.isoformat())
        + ',"business":'
        + _dumps({key: _value(value) for key, value in profile._mapping.items()})
        + ',"tables":{'
    )
    for index, table in enumerate(exported_tables()):
        yield ("," if index else "") + _dumps(table.name) + ":["
        written = 0
        batch: list[str] = []
        for row in _rows(db, table, business.id):
            batch.append(_dumps(row))
            written += 1
            if len(batch) == _BATCH_ROWS:
                yield ("," if written > _BATCH_ROWS else "") + ",".join(batch)
                batch = []
        if batch:
            yield ("," if written > len(batch) else "") + ",".join(batch)
        yield "]"
        if counts is not None:
            counts[table.name] = written
    yield (
        '},"withheld":'
        + _dumps(sorted(f"{table}.{column}" for table, column in WITHHELD))
        + "}"
    )


def export_business(db: Session, business: Business, *, exported_at: datetime) -> dict[str, Any]:
    """The whole account of *business*, as one document.

    For callers that want it in hand; the download streams :func:`iter_export`
    instead, and this is built from it so the two cannot drift apart.
    """
    return json.loads("".join(iter_export(db, business, exported_at=exported_at)))
