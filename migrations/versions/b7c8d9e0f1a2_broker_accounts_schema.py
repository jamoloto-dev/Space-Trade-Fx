"""Add broker_accounts table for MT4 and MT5 encrypted credentials

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(length=10), nullable=False),
        sa.Column("server", sa.String(length=100), nullable=False),
        sa.Column("account_login", sa.String(length=64), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("is_connected", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('MT4', 'MT5')", name="ck_broker_accounts_platform"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_broker_accounts_user_id"),
    )
    op.create_index("idx_broker_accounts_user", "broker_accounts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_broker_accounts_user", table_name="broker_accounts")
    op.drop_table("broker_accounts")
