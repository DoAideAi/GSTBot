"""Add OAuth provider fields to users table.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oauth_provider", sa.String(50), nullable=True))
    op.add_column("users", sa.Column("oauth_id", sa.String(255), nullable=True))
    # In a batch, as 0008 does. A bare alter_column renders ALTER COLUMN ...
    # DROP NOT NULL, which SQLite only learned in 3.53: the suite passed on a
    # new interpreter and failed in CI (Python 3.12's older SQLite) at this
    # line, taking every migration test with it. On Postgres the batch is the
    # same single ALTER; on SQLite it rebuilds the table.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("hashed_password", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("hashed_password", existing_type=sa.String(255), nullable=False)
    op.drop_column("users", "oauth_id")
    op.drop_column("users", "oauth_provider")
