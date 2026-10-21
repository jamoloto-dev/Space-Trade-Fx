"""Add currency, balance, equity, free_margin columns to broker_accounts

Revision ID: d1e2f3a4b5c6
Revises: c9e0f1a2b3c4
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("broker_accounts") as batch:
        batch.add_column(sa.Column("currency", sa.String(length=10), server_default="USD", nullable=False))
        batch.add_column(sa.Column("balance", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False))
        batch.add_column(sa.Column("equity", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False))
        batch.add_column(
            sa.Column("free_margin", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("broker_accounts") as batch:
        batch.drop_column("free_margin")
        batch.drop_column("equity")
        batch.drop_column("balance")
        batch.drop_column("currency")
