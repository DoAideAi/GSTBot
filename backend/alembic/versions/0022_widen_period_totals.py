"""Widen the stored period totals from numeric(16,2) to numeric(22,2).

``gstr_returns.total_*`` and ``reconciliation_runs.itc_*`` hold the sum of a
period's invoices, and each invoice may carry up to 99,999,999,999,999.99 —
so three at that ceiling summed past what numeric(16,2) holds and Postgres
refused the write. Raising the precision at the same scale is a catalogue
change only on Postgres 9.2+; no table rewrite.

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

COLUMNS = {
    "gstr_returns": (
        "total_taxable_value", "total_cgst", "total_sgst", "total_igst", "total_cess",
    ),
    "reconciliation_runs": ("itc_eligible", "itc_at_risk", "itc_claimed"),
}


def _retype(old: sa.Numeric, new: sa.Numeric) -> None:
    # Batch mode so SQLite, which has no ALTER COLUMN TYPE, rebuilds the
    # table; on Postgres it is the plain ALTER.
    for table, columns in COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.alter_column(
                    column, type_=new, existing_type=old, existing_nullable=False
                )


def upgrade() -> None:
    _retype(sa.Numeric(16, 2), sa.Numeric(22, 2))


def downgrade() -> None:
    # Fails on any row whose total no longer fits, which is the point: such a
    # row cannot be narrowed without losing it.
    _retype(sa.Numeric(22, 2), sa.Numeric(16, 2))
