"""Add webhook idempotency, auditability, and paper-order identity.

Revision ID: a31f2b8c4d9e
Revises: 58714dbcffd1
"""

from alembic import op
import sqlalchemy as sa

revision = "a31f2b8c4d9e"
down_revision = "58714dbcffd1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_stripe_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_audit_events_actor_created", "audit_events", ["actor_id", "created_at"])
    op.create_index("idx_audit_events_target", "audit_events", ["target_type", "target_id"])
    with op.batch_alter_table("licenses") as batch:
        batch.create_unique_constraint("uq_licenses_stripe_payment_id", ["stripe_payment_id"])
    op.add_column("trades", sa.Column("execution_mode", sa.String(length=20), nullable=False, server_default="paper"))
    op.add_column("trades", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.add_column("trades", sa.Column("broker_order_id", sa.String(length=100), nullable=True))
    op.add_column("trades", sa.Column("broker_response", sa.JSON(), nullable=True))
    op.add_column("trades", sa.Column("reconciliation_state", sa.String(length=32), nullable=False, server_default="not_required"))
    op.create_unique_constraint("uq_trades_idempotency_key", "trades", ["idempotency_key"])
    op.create_unique_constraint("uq_trades_broker_order_id", "trades", ["broker_order_id"])


def downgrade() -> None:
    op.drop_constraint("uq_trades_broker_order_id", "trades", type_="unique")
    op.drop_constraint("uq_trades_idempotency_key", "trades", type_="unique")
    op.drop_column("trades", "reconciliation_state")
    op.drop_column("trades", "broker_response")
    op.drop_column("trades", "broker_order_id")
    op.drop_column("trades", "idempotency_key")
    op.drop_column("trades", "execution_mode")
    with op.batch_alter_table("licenses") as batch:
        batch.drop_constraint("uq_licenses_stripe_payment_id", type_="unique")
    op.drop_index("idx_audit_events_target", table_name="audit_events")
    op.drop_index("idx_audit_events_actor_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("processed_stripe_events")
