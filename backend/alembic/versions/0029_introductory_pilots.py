"""Add bounded, one-time introductory pilots without modifying paid subscriptions.

Revision ID: 0029
Revises: 0028
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                      nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                      nullable=False)]


def upgrade():
    op.create_table(
        "pilot_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False,
                  unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("cohort_slot", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        *stamps(),
        sa.UniqueConstraint("tier", "cohort_slot", name="uq_pilot_cohort_slot"),
        sa.CheckConstraint("(tier = 'pro' AND cohort_slot BETWEEN 1 AND 20) OR "
                           "(tier = 'enterprise' AND cohort_slot BETWEEN 1 AND 10)",
                           name="ck_pilot_capacity"),
    )
    op.create_table(
        "pilot_businesses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pilot_id", sa.Integer(), sa.ForeignKey("pilot_enrollments.id"), nullable=False),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False,
                  unique=True),
        sa.Column("slot", sa.Integer(), nullable=False),
        *stamps(),
        sa.UniqueConstraint("pilot_id", "slot", name="uq_pilot_business_slot"),
        sa.CheckConstraint("slot BETWEEN 1 AND 5", name="ck_pilot_business_slot"),
    )
    op.create_index("ix_pilot_businesses_pilot_id", "pilot_businesses", ["pilot_id"])


def downgrade():
    op.drop_table("pilot_businesses")
    op.drop_table("pilot_enrollments")
