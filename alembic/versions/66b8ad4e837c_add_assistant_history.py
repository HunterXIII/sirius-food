"""Сохранить вопросы и ответы ассистента для истории пользователя."""

import sqlalchemy as sa
from alembic import op

revision = "66b8ad4e837c"
down_revision = "e94a9c612b30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assistant_replies", sa.Column("message", sa.Text()))
    op.add_column("assistant_replies", sa.Column("answer", sa.Text()))
    op.add_column("assistant_replies", sa.Column("mode", sa.String(20)))
    op.add_column("assistant_replies", sa.Column("sources", sa.JSON()))
    op.add_column("assistant_replies", sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_assistant_replies_user_created", "assistant_replies", ["user_id", "created_at", "id"],
    )


def downgrade():
    op.drop_index("ix_assistant_replies_user_created", table_name="assistant_replies")
    for column in ("created_at", "sources", "mode", "answer", "message"):
        op.drop_column("assistant_replies", column)
