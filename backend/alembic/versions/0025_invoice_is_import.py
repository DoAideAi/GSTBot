"""Mark a purchase as an import of services.

GSTR-3B claims the credit on reverse-charge tax in one of two rows: 4(A)(2)
for imported services, 4(A)(3) for every other reverse-charge purchase. With
no way to tell them apart, a cloud-hosting or ad-platform bill from abroad
put its credit in 4(A)(3), and nothing checked that it carried IGST only,
which every import of services does (IGST Act s.7(4)).

Revision ID: 0025
Revises: 0024
"""
import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added with a server default so existing rows satisfy NOT NULL, then
    # dropped, as 0003 did for is_capital_good: the model supplies the default.
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_import", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.alter_column("is_import", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("invoices", schema=None) as batch_op:
        batch_op.drop_column("is_import")
