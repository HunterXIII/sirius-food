"""Добавить векторный поиск и оценки ответов ассистента."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision = "e94a9c612b30"
down_revision = "5d7e91a0c234"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "assistant_documents",
        sa.Column("source_key", sa.String(100), primary_key=True),
        sa.Column("search_text", sa.String(), nullable=False),
        sa.Column("embedding", VECTOR(384), nullable=False),
    )
    op.create_table(
        "assistant_replies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("helpful", sa.Boolean()),
    )


def downgrade():
    op.drop_table("assistant_replies")
    op.drop_table("assistant_documents")
