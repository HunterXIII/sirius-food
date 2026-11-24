"""Сохранить correlation ID заказа для фоновой обработки оплаты."""

import sqlalchemy as sa
from alembic import op

revision = "f1a03c3fbde7"
down_revision = "2af41d90c742"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("correlation_id", sa.String(128), nullable=True))


def downgrade():
    op.drop_column("orders", "correlation_id")
