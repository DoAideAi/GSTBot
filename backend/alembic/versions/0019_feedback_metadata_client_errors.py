"""Feedback carries the visit it came from; browsers report uncaught errors.

A new revision rather than an edit to 0018: that one is already on main, and a
database that has applied it would never see a change made to it.

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("feedback", sa.Column("metadata", JSONType, nullable=True))
    op.create_table(
        "client_errors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("page", sa.String(2048), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("stack", sa.Text, nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_client_errors_last_seen_at", "client_errors", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_client_errors_last_seen_at", table_name="client_errors")
    op.drop_table("client_errors")
    op.drop_column("feedback", "metadata")
