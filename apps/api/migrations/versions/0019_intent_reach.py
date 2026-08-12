"""这条需求问谁

PRD 的"发布需求"那一段列了三档：公开投递 / 指定范围 / 熟人优先。
在这之前只有公开池。

## 它和逐项授权是两个轴，不是一个

- **授权**（`match_envelopes`）决定这次露出**什么**
- **投递范围**决定这次问**谁**

两者混成一件事，就会得到两套互相打架的可见性规则——而可见性规则一旦
互相打架，用户就再也搞不清自己的东西谁能看到。

## 「熟人」由共同完成过的事定义

不是好友列表，也不是"平台觉得你们熟"。不变量 7：关系图谱是共同事件的
可重建投影，不是平台对"熟不熟"的主观判定。

所以第一次用这个产品的人**没有熟人**——界面必须先说这件事，
再让他选，否则他会选一个必然没人可问的范围然后以为产品坏了。

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "intent_signals",
        sa.Column("reach", sa.Text, nullable=False, server_default="campus"),
    )


def downgrade() -> None:
    op.drop_column("intent_signals", "reach")
