"""paper trading integrity constraints and payment ledger

Revision ID: b8c0e42a9d1f
Revises: a31f2b8c4d9e
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c0e42a9d1f"
down_revision = "a31f2b8c4d9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode keeps the migration usable for the SQLite development/test
    # database as well as PostgreSQL production deployments.
    with op.batch_alter_table("trading_preferences") as batch:
        batch.alter_column("risk_percentage", existing_type=sa.Float(), type_=sa.Numeric(5, 2), existing_nullable=True, nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True), existing_nullable=True, nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True), existing_nullable=True, nullable=False)
        batch.create_unique_constraint("uq_trading_preferences_user", ["user_id"])
        batch.create_check_constraint("ck_trading_preferences_risk", "risk_percentage > 0 AND risk_percentage <= 2")
        batch.create_check_constraint("ck_trading_preferences_trade_limit", "max_concurrent_trades >= 1 AND max_concurrent_trades <= 20")
    with op.batch_alter_table("licenses") as batch:
        batch.alter_column("stripe_payment_id", existing_type=sa.String(100), type_=sa.String(255))
    with op.batch_alter_table("license_activations") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True), existing_nullable=True, nullable=False)
        batch.alter_column("last_check_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True), existing_nullable=True, nullable=False)
        batch.create_unique_constraint("uq_activation_license_account", ["license_id", "account_number"])
        batch.create_check_constraint("ck_activations_status", "status IN ('active', 'revoked')")
    with op.batch_alter_table("trades") as batch:
        for column in ("entry_price", "exit_price", "stop_loss", "take_profit"):
            batch.alter_column(column, existing_type=sa.Float(), type_=sa.Numeric(20, 10))
        batch.alter_column("lot_size", existing_type=sa.Float(), type_=sa.Numeric(12, 4))
        batch.alter_column("profit_loss", existing_type=sa.Float(), type_=sa.Numeric(18, 2), existing_nullable=True, nullable=False)
        batch.alter_column("opened_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
        batch.alter_column("closed_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
        batch.create_check_constraint("ck_trades_direction", "trade_type IN ('BUY', 'SELL')")
        batch.create_check_constraint("ck_trades_paper_only", "execution_mode = 'paper'")
    with op.batch_alter_table("trading_signals") as batch:
        batch.alter_column("strength", existing_type=sa.Float(), type_=sa.Numeric(5, 2))
        batch.alter_column("price", existing_type=sa.Float(), type_=sa.Numeric(20, 10))
        batch.alter_column("created_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
        batch.alter_column("expires_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
    with op.batch_alter_table("referrals") as batch:
        batch.alter_column("commission_amount", existing_type=sa.Float(), type_=sa.Numeric(18, 2), existing_nullable=True, nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
        batch.alter_column("paid_at", existing_type=sa.DateTime(), type_=sa.DateTime(timezone=True))
        batch.create_unique_constraint("uq_referrals_referred_user", ["referred_user_id"])
        batch.create_unique_constraint("uq_referrals_mentor_license", ["mentor_id", "license_id"])


def downgrade() -> None:
    # Downgrade of numeric/timestamp columns is intentionally omitted: it
    # would lose financial precision.  Restore from a verified backup instead.
    pass
