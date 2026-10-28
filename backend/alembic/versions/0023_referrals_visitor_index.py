"""Index referrals by visitor, for the sign-up conversion lookup.

``referrals.record_conversion`` runs on every registration and finds the
visitor's latest unconverted visit: WHERE visitor_ip_hash = ? ...
ORDER BY created_at DESC LIMIT 1. The only index holding the column is
uq_referrals_code_visitor, which leads with referral_code and so cannot serve
it — every sign-up scanned a table that an unauthenticated endpoint grows.
(visitor_ip_hash, created_at) answers it with a backward index scan.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

INDEX = "ix_referrals_visitor_created"


def upgrade() -> None:
    op.create_index(INDEX, "referrals", ["visitor_ip_hash", "created_at"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="referrals")
