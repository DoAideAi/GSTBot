"""Index the subscription ledger by order, for the one-order-one-period check.

verify-payment refuses a second payment for an order already applied:
WHERE razorpay_order_id = ?. The ledger's only index on a payment column is
the unique key on razorpay_payment_id, so every verify scanned the table,
while holding the business's billing lock.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

INDEX = "ix_subscription_payments_order"


def upgrade() -> None:
    op.create_index(INDEX, "subscription_payments", ["razorpay_order_id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="subscription_payments")
