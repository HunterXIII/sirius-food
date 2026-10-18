"""add categories

Revision ID: 7bb4ce2dba0d
Revises: a737c7e7ee68
Create Date: 2026-10-18 15:41:03.266115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bb4ce2dba0d'
down_revision: Union[str, None] = 'a737c7e7ee68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Таблица категорий меню.
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
    )
    # Категории - справочник, заполняем сразу (как роли в lab3).
    op.execute(
        "INSERT INTO categories (name) VALUES "
        "('Супы'), ('Горячее'), ('Гарниры'), ('Салаты'), ('Напитки'), ('Выпечка')"
    )

    # У блюда категория необязательна: у старых блюд её нет.
    op.add_column("menu_items", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_menu_items_category", "menu_items", "categories", ["category_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_menu_items_category", "menu_items", type_="foreignkey")
    op.drop_column("menu_items", "category_id")
    op.drop_table("categories")
