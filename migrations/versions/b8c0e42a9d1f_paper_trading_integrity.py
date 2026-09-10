"""paper trading integrity constraints and payment ledger

Revision ID: b8c0e42a9d1f
Revises: 58714dbcffd1
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c0e42a9d1f"
down_revision = "58714dbcffd1"
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
        batch.create_unique_constraint("uq_licenses_stripe_payment_id", ["stripe_payment_id"])
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
        batch.add_column(sa.Column("execution_mode", sa.String(20), nullable=False, server_default="paper"))
        batch.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_trades_idempotency_key", ["idempotency_key"])
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
    op.create_table(
        "processed_stripe_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])
    op.create_index("idx_audit_events_target", "audit_events", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_events_target", table_name="audit_events")
    op.drop_index("idx_audit_events_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("processed_stripe_events")
    # Downgrade of numeric/timestamp columns is intentionally omitted: it
    # would lose financial precision.  Restore from a verified backup instead.
