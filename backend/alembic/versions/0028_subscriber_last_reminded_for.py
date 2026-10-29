"""Record the last filing-deadline reminder each subscriber was sent.

Subscribers signed up for reminders that nothing sent. The reminder job writes
this after each send, so a run repeated on the same day reaches nobody twice.

Additive and nullable, so the code still running during a release is unaffected.

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("subscribers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_reminded_for", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subscribers", schema=None) as batch_op:
        batch_op.drop_column("last_reminded_for")
