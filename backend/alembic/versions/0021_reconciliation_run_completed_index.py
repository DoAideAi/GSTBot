"""Partial index for latest_completed_run() lookups.

The dashboard, the ITC summary and GSTR-3B all ask for the most recent
completed reconciliation of a period: WHERE (business_id, period,
status='completed', deleted_at IS NULL) ORDER BY created_at DESC LIMIT 1.
The existing (business_id, period) index covers the first two columns; the
database still scans and post-filters on status and deleted_at. A partial
index on (business_id, period, created_at) predicated on the two fixed
conditions lets the planner answer the query from an index-only backward
scan.

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

INDEX = "ix_reconciliation_runs_business_period_completed"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX} "
        "ON reconciliation_runs (business_id, period, created_at) "
        "WHERE deleted_at IS NULL AND status = 'completed'"
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="reconciliation_runs")
