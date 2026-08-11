"""提案的条款摘要与版本链

两条验收标准需要表结构支持：

**「实质字段变更使旧同意失效」** —— 同意是对某一版条款的同意，不是对
"这个提案"的永久授权。人选、角色、时间、地点任何一项变了，之前那句
"我加入"就不再指向现在这件事。`terms_digest` 让这件事**机器可判**，
不靠"记得去清空承诺表"。

**「条件接受生成新版本，受影响成员需重新确认」** —— 改条款是新增一行
而不是改旧行。谁在哪一版上答应过什么，申诉时要查得出来。

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "formation_proposals",
        sa.Column("terms_digest", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "formation_proposals",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("formation_proposals", sa.Column("supersedes", sa.Uuid(), nullable=True))
    op.add_column(
        "formation_proposals",
        sa.Column("withdrawn_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("formation_proposals", "withdrawn_at")
    op.drop_column("formation_proposals", "supersedes")
    op.drop_column("formation_proposals", "version")
    op.drop_column("formation_proposals", "terms_digest")
