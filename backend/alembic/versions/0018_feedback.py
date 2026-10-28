"""Store widget feedback in the database.

It went to /opt/GSTBot/feedback.json, appended by the API process — which runs
as `gstbot` under a root-owned /opt/GSTBot, so the write failed, was logged as
a warning, and the visitor was told "thanks" for feedback nobody would read.

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("page_url", sa.String(2048), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])
    op.create_index("ix_feedback_category_created", "feedback", ["category", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_category_created", table_name="feedback")
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
