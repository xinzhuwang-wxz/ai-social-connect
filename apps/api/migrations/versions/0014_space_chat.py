"""成局之后的群聊

**和成局前的受限协商是两回事。** `negotiation_messages` 的每一句都是一次
披露事件，所以只有七种结构化类型、没有一种构成同意。而这里的人已经在
同一个组里了——他们本来就该能自由说话。约束的理由消失了，约束就该消失。

**也不塞进 `space_items`。** 条目有状态、有负责人、有截止时刻、进不进度；
消息一样都没有。混在一起，"做完了多少"会被聊天量冲淡——而不变量 6 说的
正是空间因真实行动证据生长，不因聊天量生长。

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "space_messages",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("space_id", sa.Uuid, nullable=False),
        sa.Column("author_id", sa.Uuid, nullable=False),
        sa.Column("is_agent", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("kind", sa.Text, nullable=False, server_default="said"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("replies_to", sa.Uuid),
        sa.Column("about_item_id", sa.Uuid),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_messages_space_time", "space_messages", ["campus_id", "space_id", "created_at"]
    )
    op.create_index("ix_messages_thread", "space_messages", ["campus_id", "replies_to"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON space_messages TO {APP_ROLE}")
    op.execute("ALTER TABLE space_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE space_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY space_messages_campus_isolation ON space_messages
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS space_messages_campus_isolation ON space_messages"
    )
    op.drop_table("space_messages")
