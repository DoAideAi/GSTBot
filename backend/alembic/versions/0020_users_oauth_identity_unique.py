"""One account per social sign-in identity, enforced and indexed.

Every Google, GitHub or Microsoft sign-in looks the user up by
(oauth_provider, oauth_id), and nothing indexed or constrained the pair: a
scan of every user on each login, and nothing stopping one provider account
from ending up linked to two users.

Before the index is built, existing data is made to satisfy it. An empty
oauth_id is not an identity — the routes once stored "" when a provider's
response had no id — so those links are cleared; and where two users hold the
same identity, the earliest keeps it and the later ones are unlinked (they
still sign in with their password or by email). The users table is small, so
a plain CREATE INDEX holds its lock for moments, not minutes.

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

INDEX = "uq_users_oauth_identity"


def upgrade() -> None:
    op.execute(
        "UPDATE users SET oauth_provider = NULL, oauth_id = NULL WHERE oauth_id = ''"
    )
    op.execute(
        """
        UPDATE users SET oauth_provider = NULL, oauth_id = NULL
        WHERE oauth_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM users AS earlier
            WHERE earlier.oauth_provider = users.oauth_provider
              AND earlier.oauth_id = users.oauth_id
              AND earlier.id < users.id
        )
        """
    )
    op.create_index(
        INDEX,
        "users",
        ["oauth_provider", "oauth_id"],
        unique=True,
        sqlite_where=sa.text("oauth_id IS NOT NULL"),
        postgresql_where=sa.text("oauth_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="users")
