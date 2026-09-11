"""reconcile schema drift between models and migrations

Revision ID: 9ddf60f1d4ee
Revises: c41e8d7f2a90
Create Date: 2026-09-11 03:52:29.741725
"""

from alembic import op
import sqlalchemy as sa


revision = "9ddf60f1d4ee"
down_revision = "c41e8d7f2a90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize any legacy null values before enforcing non-null constraints
    op.execute("UPDATE users SET total_commission = 0 WHERE total_commission IS NULL")
    op.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    op.execute("UPDATE licenses SET issued_at = CURRENT_TIMESTAMP WHERE issued_at IS NULL")
    op.execute("UPDATE licenses SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE licenses SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    op.execute("UPDATE notifications SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE referrals SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE trades SET status = 'draft' WHERE status IS NULL")
    op.execute("UPDATE trades SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.execute("UPDATE trades SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    op.execute("UPDATE trading_signals SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.VARCHAR(), nullable=False)
        batch.alter_column("total_commission", existing_type=sa.FLOAT(), type_=sa.Numeric(18, 2), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("licenses") as batch:
        batch.alter_column("issued_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("trades") as batch:
        batch.alter_column("status", existing_type=sa.VARCHAR(length=20), type_=sa.String(length=32), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)
        # Keep broker correlation fields in the ledger.  They are nullable so
        # paper-only trades remain valid, while acknowledged broker adapters
        # can persist an id and raw response for reconciliation.

    with op.batch_alter_table("trading_signals") as batch:
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("notifications") as batch:
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)

    with op.batch_alter_table("referrals") as batch:
        batch.alter_column("created_at", existing_type=sa.DATETIME(), type_=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    pass
