"""timezone aware licenses expires_at and broker_order_id constraint

Revision ID: a1b2c3d4e5f6
Revises: f4a8b79c1e03
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "f4a8b79c1e03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    trade_constraints = {constraint.get("name") for constraint in inspector.get_unique_constraints("trades")}
    with op.batch_alter_table("licenses") as batch:
        batch.alter_column(
            "expires_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
    with op.batch_alter_table("trades") as batch:
        if "uq_trades_broker_order_id" not in trade_constraints:
            batch.create_unique_constraint("uq_trades_broker_order_id", ["broker_order_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    trade_constraints = {constraint.get("name") for constraint in inspector.get_unique_constraints("trades")}
    with op.batch_alter_table("trades") as batch:
        if "uq_trades_broker_order_id" in trade_constraints:
            batch.drop_constraint("uq_trades_broker_order_id", type_="unique")
    with op.batch_alter_table("licenses") as batch:
        batch.alter_column(
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
        )
