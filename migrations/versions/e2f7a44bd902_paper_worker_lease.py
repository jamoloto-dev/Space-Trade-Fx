"""add a lease for the standalone paper lifecycle worker

Revision ID: e2f7a44bd902
Revises: 9ddf60f1d4ee
"""

from alembic import op
import sqlalchemy as sa


revision = "e2f7a44bd902"
down_revision = "9ddf60f1d4ee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_worker_leases",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("paper_worker_leases")
