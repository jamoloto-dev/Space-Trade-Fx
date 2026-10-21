"""Purge paper-only constraint and support live/demo broker execution

Revision ID: c9e0f1a2b3c4
Revises: b7c8d9e0f1a2
"""

from alembic import op
import sqlalchemy as sa


revision = "c9e0f1a2b3c4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_uniques = {c.get("name") for c in inspector.get_unique_constraints("trades")}
    existing_checks = {c.get("name") for c in inspector.get_check_constraints("trades")}

    with op.batch_alter_table("trades") as batch:
        batch.alter_column(
            "execution_mode",
            existing_type=sa.String(length=20),
            server_default="broker",
            nullable=False,
        )
        if "ck_trades_paper_only" in existing_checks:
            batch.drop_constraint("ck_trades_paper_only", type_="check")
        if "ck_trades_execution_mode" not in existing_checks:
            batch.create_check_constraint(
                "ck_trades_execution_mode",
                "execution_mode IN ('broker', 'live', 'demo', 'paper')",
            )
        if "uq_trades_broker_order_id" not in existing_uniques:
            batch.create_unique_constraint("uq_trades_broker_order_id", ["broker_order_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_uniques = {c.get("name") for c in inspector.get_unique_constraints("trades")}
    existing_checks = {c.get("name") for c in inspector.get_check_constraints("trades")}

    with op.batch_alter_table("trades") as batch:
        batch.alter_column(
            "execution_mode",
            existing_type=sa.String(length=20),
            server_default="paper",
            nullable=False,
        )
        if "ck_trades_execution_mode" in existing_checks:
            batch.drop_constraint("ck_trades_execution_mode", type_="check")
        if "ck_trades_paper_only" not in existing_checks:
            batch.create_check_constraint("ck_trades_paper_only", "execution_mode = 'paper'")
        if "uq_trades_broker_order_id" in existing_uniques:
            batch.drop_constraint("uq_trades_broker_order_id", type_="unique")
