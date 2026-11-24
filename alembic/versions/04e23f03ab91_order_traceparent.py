"""Сохранить W3C traceparent до подтверждения оплаты."""

import sqlalchemy as sa
from alembic import op

revision = "04e23f03ab91"
down_revision = "f1a03c3fbde7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("traceparent", sa.String(55), nullable=True))


def downgrade():
    op.drop_column("orders", "traceparent")
