"""我想参与这类事

## 这一列补的是产品里最大的一个洞

在它之前，一个真人只有两条被找到的路：`skills`（我会什么）和
`self_intro`（我是什么风格）。**两条都不是"我最近想干什么"。**

后果比缺一个字段严重得多：漏斗第一段写死了 `skills && needs`，而**没有
任何接口能写 `skills`**——真人注册完这一列永远是空的，于是

    两个真人永远不可能出现在同一个提案里。

合成人口有技能（装载时直接写的），所以仿真里一切正常；真人对真人是死的。
而合成主体又不能与真人同局（`formation.eligibility`）。**这个产品最核心
的那件事，对真实用户从来没有成立过。**

## 为什么不复用 `skills`

因为它们在求解器里的地位必须不同：

- `skills` 是**我能补上的洞**。ROLE_COVERAGE 这条硬约束只认它
- `open_to` 是**我想参与的方向**。它只放宽召回，不放宽承诺

一个说"我想参与拍短片"的人可以被叫来一起做，但永远不会被当成会剪辑的人
塞进剪辑那个坑里。两件事共用一列就分不开了。

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "principals",
        sa.Column(
            "open_to",
            ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    # 和 `skills` 一样走 GIN：漏斗第一段用 `&&` 重叠运算符，
    # 而重叠查询没有 GIN 就是全表扫。
    op.create_index(
        "ix_principals_open_to",
        "principals",
        ["open_to"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_principals_open_to", table_name="principals")
    op.drop_column("principals", "open_to")
