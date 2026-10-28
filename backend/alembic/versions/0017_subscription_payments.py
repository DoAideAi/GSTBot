"""Record every payment applied to a subscription.

The subscription row keeps only the latest payment id, so verify-payment could
tell a replay of *that* payment but not of an earlier one: re-verifying an old,
genuinely paid order added another period each time. One row per applied
payment, unique across tenants, makes a payment usable once.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "business_id",
            sa.Integer,
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=False, unique=True),
        sa.Column("razorpay_order_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("amount_paise", sa.Integer, nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_subscription_payments_business_id", "subscription_payments", ["business_id"]
    )
    op.create_index(
        "ix_subscription_payments_business_created",
        "subscription_payments",
        ["business_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("subscription_payments")
