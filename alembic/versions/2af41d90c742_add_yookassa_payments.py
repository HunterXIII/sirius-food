"""Store YooKassa payments and delivery refunds."""

import sqlalchemy as sa
from alembic import op

revision = "2af41d90c742"
down_revision = "5a7c0d93ef41"
branch_labels = None
depends_on = None


def operation_columns():
    return (
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gateway_id", sa.String(64), unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_sent_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade():
    op.add_column("orders", sa.Column("total_amount", sa.Numeric(12, 2)))
    op.add_column("orders", sa.Column("cancellation_reason", sa.Text()))
    op.create_table(
        "payments",
        *operation_columns(),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("expected_amount", sa.Numeric(12, 2)),
        sa.Column("return_url", sa.Text(), nullable=False),
        sa.Column("confirmation_url", sa.Text()),
        sa.Column("paid_event_id", sa.String(36), unique=True),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_key"),
        sa.CheckConstraint("amount > 0", name="ck_payments_positive_amount"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_next_check_at", "payments", ["next_check_at"])
    op.create_index(
        "uq_payments_open_or_paid_order", "payments", ["order_id"], unique=True,
        postgresql_where=sa.text("status <> 'canceled'"),
    )
    op.create_table(
        "refunds",
        *operation_columns(),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.CheckConstraint("amount > 0", name="ck_refunds_positive_amount"),
    )
    op.create_index("ix_refunds_next_check_at", "refunds", ["next_check_at"])


def downgrade():
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_column("orders", "cancellation_reason")
    op.drop_column("orders", "total_amount")
