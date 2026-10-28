"""Contract checks over the mapper registry.

The tenancy sweeps in ``test_tenancy_contract.py`` prove that a scoped route
cannot read another tenant's row. These prove the layer underneath: that the
*table* is shaped so the scoped query it runs is cheap, and that a new scoped
model cannot be added without that shape.

That guarantee used to be claimed by ``BusinessScopedMixin.__table_args__``,
which built the ``(business_id, created_at)`` index from ``__tablename__``. It
never applied to a single table. Every scoped model declares its own
``__table_args__`` — for a partial unique constraint, or a second composite
index — and a class attribute shadows an inherited ``declared_attr`` outright
rather than merging with it. The index existed on all five tables only because
each model also spelled it out by hand, which is exactly the per-model habit
the mixin was written to remove.

So the guarantee is asserted here instead. A sweep cannot be shadowed by the
next model, and unlike the mixin it fails loudly when the index is missing
rather than looking like it was inherited.
"""
from __future__ import annotations

import pytest
from sqlalchemy import UniqueConstraint

import app.models  # noqa: F401  -- registers every model on Base.metadata
from app.core.database import Base
from app.models.mixins import BusinessScopedMixin


def _scoped_mappers() -> list:
    """Every mapped class inheriting ``BusinessScopedMixin``.

    Read off the registry rather than an explicit list: a list is a second
    place to update, and the model that forgets to update it is the model this
    file exists to catch.
    """
    return sorted(
        (
            m
            for m in Base.registry.mappers
            if issubclass(m.class_, BusinessScopedMixin)
        ),
        key=lambda m: m.class_.__tablename__,
    )


def _scoped_params() -> list:
    return [pytest.param(m, id=m.class_.__tablename__) for m in _scoped_mappers()]


SCOPED = _scoped_params()


def test_the_registry_sweep_is_actually_looking_at_the_scoped_models() -> None:
    """Guard the guard.

    Every assertion below is parametrized over ``_scoped_mappers()``. If that
    ever returns nothing — a renamed mixin, a registry API change, a models
    package that stops importing its submodules — pytest reports the whole
    file as passing with zero cases rather than as broken. Name the tables so
    the sweep going empty or silently shrinking is a red test.
    """
    tables = {m.class_.__tablename__ for m in _scoped_mappers()}
    assert tables == {
        "alerts",
        "gstr_returns",
        "invoices",
        "reconciliation_runs",
        "report_purchases",
        "suppliers",
    }


@pytest.mark.parametrize("mapper", SCOPED)
def test_every_business_scoped_table_can_list_a_tenants_rows_newest_first_on_an_index(
    mapper,
) -> None:
    """A composite ``(business_id, created_at)`` index, in that column order.

    Every list endpoint in the product is "this tenant's rows, newest first,
    paginated". On ``business_id`` alone that reads every row the tenant owns
    and sorts it to return twenty; the composite lets the planner walk the
    index and stop. Order matters and is not interchangeable: ``created_at``
    first cannot serve the equality on ``business_id``.
    """
    table = mapper.class_.__table__
    wanted = ("business_id", "created_at")
    matching = [ix for ix in table.indexes if tuple(c.name for c in ix.columns) == wanted]
    assert matching, (
        f"{table.name} is business-scoped but has no {wanted} index. "
        f"Declare it in the model's own __table_args__ — inheriting it from "
        f"BusinessScopedMixin does not work, see this module's docstring. "
        f"Indexes present: "
        f"{sorted(tuple(c.name for c in ix.columns) for ix in table.indexes)}"
    )


@pytest.mark.parametrize("mapper", SCOPED)
def test_every_business_scoped_table_refuses_a_row_with_no_tenant(mapper) -> None:
    """``business_id`` is NOT NULL and points at ``businesses`` with a cascade.

    A nullable tenant column is the one shape the tenancy sweeps cannot catch:
    a row with ``business_id IS NULL`` is filtered out by every scoped query,
    so it never appears in a cross-tenant read and never 404s — it simply goes
    missing, and the tenant who wrote it opens a support ticket.
    """
    column = mapper.class_.__table__.c.business_id
    assert not column.nullable, f"{mapper.class_.__tablename__}.business_id is nullable"

    targets = {fk.column.table.name for fk in column.foreign_keys}
    assert targets == {"businesses"}, (
        f"{mapper.class_.__tablename__}.business_id points at {targets or 'nothing'}"
    )
    assert all(fk.ondelete == "CASCADE" for fk in column.foreign_keys)


@pytest.mark.parametrize("mapper", SCOPED)
def test_every_business_scoped_table_is_soft_deleted_and_indexes_the_tombstone(
    mapper,
) -> None:
    """Scoped data is business data, and business data is never hard-deleted.

    The pairing is the point: ``deleted_at`` without an index means every
    scoped read pays to filter tombstones it cannot skip, and the partial
    unique indexes predicated on ``deleted_at IS NULL`` need it too.
    """
    table = mapper.class_.__table__
    assert "deleted_at" in table.c, f"{table.name} is scoped but not soft-deleted"
    assert table.c.deleted_at.nullable

    indexed = any(
        "deleted_at" in {c.name for c in ix.columns} for ix in table.indexes
    )
    assert indexed, f"{table.name}.deleted_at is not indexed"


@pytest.mark.parametrize("mapper", SCOPED)
def test_every_business_scoped_table_carries_both_timestamps(mapper) -> None:
    """``created_at`` must exist and be non-null for the composite index above
    to be worth having — an index whose second column is mostly NULL sorts
    nothing useful — and ``updated_at`` is what the digest tasks read to decide
    what changed since the last run."""
    table = mapper.class_.__table__
    for name in ("created_at", "updated_at"):
        assert name in table.c, f"{table.name} has no {name}"
        assert not table.c[name].nullable, f"{table.name}.{name} is nullable"


@pytest.mark.parametrize("mapper", SCOPED)
def test_every_business_scoped_uniqueness_rule_is_scoped_to_one_tenant(mapper) -> None:
    """A unique rule on a scoped table must lead with ``business_id``.

    Without it the constraint is global: the first tenant to file ``2026-04``
    takes that period away from every other tenant on the box, and the second
    tenant's import fails with an integrity error naming a row they are not
    allowed to see. Cross-tenant collisions are a data-isolation bug that
    presents as a 500.
    """
    table = mapper.class_.__table__
    rules = [
        (ix.name, [c.name for c in ix.columns]) for ix in table.indexes if ix.unique
    ] + [
        (uc.name, [c.name for c in uc.columns])
        for uc in table.constraints
        if isinstance(uc, UniqueConstraint)
    ]
    for name, columns in rules:
        assert columns[0] == "business_id", (
            f"{table.name}.{name} is unique over {columns} — not tenant-scoped"
        )
