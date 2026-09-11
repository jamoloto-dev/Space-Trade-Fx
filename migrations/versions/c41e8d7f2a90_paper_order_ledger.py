"""add immutable paper order events and reconciliation runs

Revision ID: c41e8d7f2a90
Revises: b8c0e42a9d1f
"""

from alembic import op
import sqlalchemy as sa


revision = "c41e8d7f2a90"
down_revision = "b8c0e42a9d1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The prior paper-only migration may have left the earlier placeholder
    # value in existing databases. Normalize it before enforcing the enum.
    op.execute("UPDATE trades SET reconciliation_state = 'pending' WHERE reconciliation_state IS NULL OR reconciliation_state = 'not_required'")
    with op.batch_alter_table("trades") as batch:
        batch.alter_column("reconciliation_state", existing_type=sa.String(32), type_=sa.String(20), nullable=False, server_default="pending")
        batch.add_column(sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_trades_reconciliation_state", "reconciliation_state IN ('pending', 'reconciled', 'exception')")
    op.create_table(
        "paper_order_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("state_before", sa.String(32), nullable=True),
        sa.Column("state_after", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trade_id", "sequence", name="uq_paper_order_events_trade_sequence"),
        sa.CheckConstraint("event_type IN ('intent_recorded', 'risk_validated', 'opened', 'close_requested', 'closed', 'rejected', 'reconciled', 'reconciliation_exception')", name="ck_paper_order_events_type"),
    )
    op.create_index("idx_paper_order_events_trade_created", "paper_order_events", ["trade_id", "created_at"])
    op.create_table(
        "paper_reconciliation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checked_count", sa.Integer(), nullable=False),
        sa.Column("exception_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("paper_reconciliation_runs")
    op.drop_index("idx_paper_order_events_trade_created", table_name="paper_order_events")
    op.drop_table("paper_order_events")
    with op.batch_alter_table("trades") as batch:
        batch.drop_constraint("ck_trades_reconciliation_state", type_="check")
        batch.drop_column("last_reconciled_at")
