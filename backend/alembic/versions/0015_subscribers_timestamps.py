"""Give subscribers created_at / updated_at like every other mutable table.

``subscribed_at`` is not a creation time: resubscribing rewrites it on the same
row (``_upsert_subscriber``), and unsubscribing changes the row without
recording when. So a row could not say when the address first signed up, nor
when it last changed. Every other table that is updated after insert carries
``TimestampMixin``; this one now does too.

Backfilled from ``subscribed_at`` — the earliest moment the row still knows.
For a row that was resubscribed that is later than the truth, which is the
loss this migration stops, not one it can undo. ``updated_at`` takes the later
of the subscribe and unsubscribe moments.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscribers",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "subscribers",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE subscribers
           SET created_at = subscribed_at,
               updated_at = CASE
                   WHEN unsubscribed_at IS NOT NULL AND unsubscribed_at > subscribed_at
                   THEN unsubscribed_at
                   ELSE subscribed_at
               END
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("subscribers") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
