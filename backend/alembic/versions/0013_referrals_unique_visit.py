"""One referral row per (code, visitor), enforced by the database.

``POST /referrals/track`` de-duplicated with a read-then-insert, so two
requests from the same visitor in flight together both saw "not tracked" and
both inserted — and every referral count and the leaderboard read the
duplicates as separate visits. The constraint makes the database the one that
decides; the route catches the loser.

Existing duplicates are deleted first, keeping the earliest row of each pair,
or the constraint could not be created on a database that already has them.
That loses nothing the product reads: the rows are identical apart from
``id`` and ``created_at``, and ``converted`` is never set to true.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

CONSTRAINT = "uq_referrals_code_visitor"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM referrals
         WHERE id NOT IN (
             SELECT MIN(id) FROM referrals GROUP BY referral_code, visitor_ip_hash
         )
        """
    )
    with op.batch_alter_table("referrals") as batch:
        batch.create_unique_constraint(CONSTRAINT, ["referral_code", "visitor_ip_hash"])


def downgrade() -> None:
    # The deleted duplicates are not restored; they carried nothing to restore.
    with op.batch_alter_table("referrals") as batch:
        batch.drop_constraint(CONSTRAINT, type_="unique")
