"""Связать ответы ассистента со спанами Phoenix."""

import sqlalchemy as sa
from alembic import op

revision = "5a7c0d93ef41"
down_revision = "812f319f0130"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assistant_replies", sa.Column("phoenix_span_id", sa.String(16)))


def downgrade():
    op.drop_column("assistant_replies", "phoenix_span_id")
