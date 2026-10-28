"""Add report_purchases: one row per paid PDF report of a reconciliation run.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_purchases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "business_id",
            sa.Integer,
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("razorpay_order_id", sa.String(64), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=False),
        sa.Column("amount_paise", sa.Integer, nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "business_id", "razorpay_order_id", name="uq_report_purchases_business_order"
        ),
        sa.UniqueConstraint(
            "business_id", "razorpay_payment_id", name="uq_report_purchases_business_payment"
        ),
    )
    op.create_index("ix_report_purchases_business_id", "report_purchases", ["business_id"])
    op.create_index("ix_report_purchases_run_id", "report_purchases", ["run_id"])
    op.create_index("ix_report_purchases_deleted_at", "report_purchases", ["deleted_at"])
    op.create_index(
        "ix_report_purchases_business_created",
        "report_purchases",
        ["business_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("report_purchases")
