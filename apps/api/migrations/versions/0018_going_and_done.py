"""到那天了：我准备好了、我出发了、我到了；以及全员点完成

PRD 的「线下转化」这一段在这之前整个不存在。产品能把人凑齐、能定下计划，
然后**就到此为止**——而 PRD 说得很清楚：这个产品不是以"双方聊起来"为终点，
是以"真的一起完成了一次行动"为终点。

## 为什么状态是一张小表，不是空间条目

条目是"要做的事"：有负责人、有截止、进不进度。而"我出发了"不是一件事，
是**一个人此刻的处境**，它每人只有一条、会来回改、行动结束就没意义了。
混进条目里，进度条会被一堆"我到了"顶满。

## 为什么不做持续定位

PRD 自己写的：首版不需要持续定位，只需要地址入口和必要状态。
一个为了"看谁到了"而常开的定位权限，换来的信息量还不如一句"我到了"。

## 完成要全员点头，和确认计划同一条理由

一个人说"做完了"就把事情标记成完成，等于让他替所有人宣布。
而这件事会写进每个人的森林。

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "day_of_states",
        sa.Column("space_id", sa.Uuid, primary_key=True),
        sa.Column("principal_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        #: ready / leaving / arrived / changed
        sa.Column("state", sa.Text, nullable=False),
        #: 「临时有变」得能说一句为什么——不说就只是一个让人干着急的标记。
        sa.Column("note", sa.Text),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_day_of_campus", "day_of_states", ["campus_id"])

    op.create_table(
        "done_marks",
        sa.Column("space_id", sa.Uuid, primary_key=True),
        sa.Column("principal_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("marked_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_done_campus", "done_marks", ["campus_id"])

    for table in ("day_of_states", "done_marks"):
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
    op.drop_table("done_marks")
    op.drop_table("day_of_states")
