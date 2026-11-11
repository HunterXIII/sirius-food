"""Разделить историю ассистента на чаты."""

import sqlalchemy as sa
from alembic import op

revision = "812f319f0130"
down_revision = "66b8ad4e837c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assistant_chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    )
    op.add_column("assistant_replies", sa.Column("chat_id", sa.String(36)))
    op.execute("""
        INSERT INTO assistant_chats (id, user_id)
        SELECT gen_random_uuid()::text, user_id
        FROM assistant_replies
        WHERE created_at IS NOT NULL
        GROUP BY user_id
    """)
    op.execute("""
        UPDATE assistant_replies AS reply
        SET chat_id = chat.id
        FROM assistant_chats AS chat
        WHERE chat.user_id = reply.user_id AND reply.created_at IS NOT NULL
    """)
    op.create_foreign_key("fk_assistant_replies_chat", "assistant_replies", "assistant_chats", ["chat_id"], ["id"])
    op.create_index("ix_assistant_replies_chat_created", "assistant_replies", ["chat_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_assistant_replies_chat_created", table_name="assistant_replies")
    op.drop_constraint("fk_assistant_replies_chat", "assistant_replies", type_="foreignkey")
    op.drop_column("assistant_replies", "chat_id")
    op.drop_table("assistant_chats")
