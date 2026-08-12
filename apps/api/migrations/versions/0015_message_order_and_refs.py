"""消息的顺序要可靠，指向要指得回去

三个真 bug，都由测试暴露：

**① 同一时刻内的顺序是随机的。** 排序键是 `(created_at, id)`，而 `id` 是
`uuid4()`。`raise_topics` 用同一个 `now` 一次落两张话题卡，于是那两张卡
每读一次先后都可能不一样——界面上它们会自己换位置。兜底键必须单调。

**② `replies_to` 不校验。** 回复一条回复、或指向一个随机 uuid，都会被接受，
然后在 `threads()` 里**消失**——只在平铺列表里出现。「只有一层」原本是
组装时保证的，代价是消息被静默吞掉，而静默正是这个项目一路在修的失败模式。

**③ `about_item_id` 只校验非空。** 不检查条目存不存在、在不在这个空间。
于是那条判断的实际含义是「非空」而不是「指得回一件还没定的事」。

②③ 的完整修法在应用层（要判断"是不是话题卡"、"是不是还没定"），
这里先把**外键**补上——数据库能挡住的部分不该留给应用记得挡。

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 单调序号。`created_at` 相同时靠它定先后——随机 UUID 做不到这件事。
    op.add_column(
        "space_messages",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
    )
    op.create_index(
        "ix_messages_space_seq", "space_messages", ["campus_id", "space_id", "seq"]
    )
    # 回复只能挂在这张表里真实存在的一条消息上。
    # 指向一个随机 uuid 的回复会在任何视图里消失，而消失比报错糟得多。
    op.create_foreign_key(
        "fk_messages_replies_to",
        "space_messages",
        "space_messages",
        ["replies_to"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_messages_replies_to", "space_messages", type_="foreignkey")
    op.drop_index("ix_messages_space_seq", table_name="space_messages")
    op.drop_column("space_messages", "seq")
