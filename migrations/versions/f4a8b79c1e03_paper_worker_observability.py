"""scope paper idempotency to users and add worker health state

Revision ID: f4a8b79c1e03
Revises: e2f7a44bd902
"""

from alembic import op
import sqlalchemy as sa


revision = "f4a8b79c1e03"
down_revision = "e2f7a44bd902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The former global constraint means existing data is already safe to
    # widen to a per-user key.  Keep the old migration immutable for deployed
    # databases and make this compatibility change forward-only.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    trade_columns = {column["name"] for column in inspector.get_columns("trades")}
    trade_constraints = {constraint.get("name") for constraint in inspector.get_unique_constraints("trades")}
    with op.batch_alter_table("trades") as batch:
        # Some early local databases were stamped at the reconciliation
        # revision despite having been created before these nullable ledger
        # fields existed.  Adding them is data-preserving and keeps those
        # supported installations upgradeable; no broker value is generated.
        if "mt5_ticket" not in trade_columns:
            batch.add_column(sa.Column("mt5_ticket", sa.String(length=50), nullable=True))
        if "broker_order_id" not in trade_columns:
            batch.add_column(sa.Column("broker_order_id", sa.String(length=100), nullable=True))
        if "broker_response" not in trade_columns:
            batch.add_column(sa.Column("broker_response", sa.JSON(), nullable=True))
        if "uq_trades_idempotency_key" in trade_constraints:
            batch.drop_constraint("uq_trades_idempotency_key", type_="unique")
        if "uq_trades_user_idempotency_key" not in trade_constraints:
            batch.create_unique_constraint("uq_trades_user_idempotency_key", ["user_id", "idempotency_key"])
    with op.batch_alter_table("paper_worker_leases") as batch:
        batch.add_column(sa.Column("last_cycle_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(length=250), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("paper_worker_leases") as batch:
        batch.drop_column("last_error")
        batch.drop_column("last_success_at")
        batch.drop_column("last_cycle_at")
    with op.batch_alter_table("trades") as batch:
        batch.drop_constraint("uq_trades_user_idempotency_key", type_="unique")
        batch.create_unique_constraint("uq_trades_idempotency_key", ["idempotency_key"])
