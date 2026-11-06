"""Таблицы кухни, идемпотентности и Transactional Outbox (lab7)."""
from alembic import op
import sqlalchemy as sa

revision = "5d7e91a0c234"
down_revision = "cd69256dbf7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kitchen_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
    )
    op.create_table(
        "processed_events",
        sa.Column("consumer", sa.String(50), primary_key=True),
        sa.Column("id", sa.String(36), primary_key=True),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("routing_key", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_outbox_published", "outbox", ["published"])


def downgrade() -> None:
    op.drop_index("ix_outbox_published", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("processed_events")
    op.drop_table("kitchen_orders")
