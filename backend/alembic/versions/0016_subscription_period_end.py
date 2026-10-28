"""Give a subscription the end of the period it was paid for.

Checkout is a one-time Razorpay order at the monthly or annual price. Nothing
recorded how long that bought, and the only path to ``expired`` is a Razorpay
``subscription.expired`` webhook — which never comes, because no Razorpay
subscription exists. So one monthly payment kept a business on PRO forever.

Nullable, and left null for existing rows: they were sold without an end, and
cutting them off by inference would be its own bug. New payments set it.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.drop_column("current_period_end")
