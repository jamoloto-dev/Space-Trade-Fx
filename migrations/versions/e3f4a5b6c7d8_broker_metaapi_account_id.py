"""Add metaapi_account_id column to broker_accounts

Revision ID: e3f4a5b6c7d8
Revises: d1e2f3a4b5c6
"""

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("broker_accounts") as batch:
        batch.add_column(sa.Column("metaapi_account_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("broker_accounts") as batch:
        batch.drop_column("metaapi_account_id")
