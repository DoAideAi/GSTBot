"""Record when a user last changed their password.

There was no way to change a password, so one that leaked could not be rotated,
and the tokens it had issued stayed good for their full lifetime. The change
route sets this, and a token issued before it is refused.

Additive and nullable, so the code still running during a release is unaffected.

Revision ID: 0026
Revises: 0025
"""
import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("password_changed_at")
