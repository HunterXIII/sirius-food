"""add orders created_at

Revision ID: cd69256dbf7b
Revises: 7bb4ce2dba0d
Create Date: 2026-10-19 16:00:16.274897

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd69256dbf7b'
down_revision: Union[str, None] = '7bb4ce2dba0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Время создания заказа - для статистики заказов за день (Celery Beat).
    # У старых заказов времени нет (NULL): когда они созданы, уже не узнать.
    op.add_column("orders", sa.Column("created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "created_at")
