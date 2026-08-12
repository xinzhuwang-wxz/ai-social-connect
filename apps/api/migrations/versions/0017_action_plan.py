"""行动确认卡：从"有空一起"变成"确定一起"

PRD 把它称作**最重要的中间转化节点**，而在这之前它整个不存在。

## 它和成局确认不是一回事

成局那道门问的是「要不要和这几个人组队」；这张卡问的是
「我们要做的到底是什么」——几点、在哪、带什么、谁负责哪一样。

两件事混在一张卡上，用户点一次头就同时答应了两个不同的问题，
而"他同意的是哪一个"事后查不出来。

## 改了计划就得重新点头

和成局条款同一条逻辑：`digest` 是这一版内容的摘要，任何一项改动都换一个
摘要，而**点头是记在摘要上的**。于是"我点头的时候地点是北门，后来被改成
南门"这件事不可能发生——地点一改，所有人的点头一起失效。

不用"改动后清空点头"而用摘要，是因为前者依赖每一处写路径都记得清；
后者由数据本身保证。

## 任务和负责人不复制到这张卡上

它们已经在 `space_items` 里了。复制一份的代价是两处会不一致，
而不一致的那一刻，用户看到的是两个都像真的的计划。

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "action_plans",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("space_id", sa.Uuid, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        #: 什么时候。空表示还没定——**没定就是没定，不猜一个**。
        sa.Column("starts_at", sa.TIMESTAMP(timezone=True)),
        #: 在哪集合。
        sa.Column("place", sa.Text),
        #: 要带什么。一行一样。
        sa.Column("bring", sa.Text),
        #: 大概多少钱。说不清就空着，编一个数比不说更糟。
        sa.Column("budget", sa.Text),
        #: 有变怎么办。PRD 明确要求这一项——临时变更是行动最常见的死因。
        sa.Column("change_note", sa.Text),
        #: 这一版内容的摘要。点头记在它上面。
        sa.Column("digest", sa.Text, nullable=False),
        sa.Column("created_by", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # 一个空间只有一张现行的卡。历史在事件那边，这里只放当前状态。
        sa.UniqueConstraint("space_id", name="uq_plan_per_space"),
    )
    op.create_index("ix_plans_campus", "action_plans", ["campus_id"])

    op.create_table(
        "plan_nods",
        sa.Column("plan_id", sa.Uuid, primary_key=True),
        sa.Column("principal_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        #: 他点头时那一版的摘要。和现行摘要对不上，这一次点头就不算数。
        sa.Column("digest", sa.Text, nullable=False),
        sa.Column("nodded_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_nods_campus", "plan_nods", ["campus_id"])

    for table in ("action_plans", "plan_nods"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_campus_isolation ON {table}
            TO {APP_ROLE}
            USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
            WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
            """
        )


def downgrade() -> None:
    op.drop_table("plan_nods")
    op.drop_table("action_plans")
