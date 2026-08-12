"""投递制：种子投给多人，候选表态，发起人挑到收满

## 为什么改掉整组求解

旧链路让发起人**把勇气花在一次抛硬币上**——挑一支队，然后等对方理不理你。
而"石沉大海"正是这个产品要消灭的第二个痛点。

新链路：种子投给多个候选 → 候选表态「愿意参与」→ 发起人**在已经说了愿意
的人里挑**，挑到种子要的人数收满为止。发起人面对的每一个人都已经说过愿意。

代价是从同步变异步。值得。

## 为什么是一张新表而不是复用提案

提案是"这几个人组成的一支队，等大家点头"。投递是"这颗种子到了你这里"——
它是**一对一**的，每个候选各自一条，各自有自己的状态和留言。

塞进 `formation_proposals` 的话，`member_ids` 那一列会同时表示两种东西：
一支队的成员，和一批互不相干的候选人。而那正是"一个字段两种含义"的开始。

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "seed_deliveries",
        sa.Column("intent_id", sa.Uuid, primary_key=True),
        sa.Column("principal_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        #: delivered / willing / passed / chosen / closed
        sa.Column("state", sa.Text, nullable=False, server_default="delivered"),
        #: 说「愿意」时可以附一句话。**可选**——要求写理由会让人不敢点愿意。
        sa.Column("note", sa.Text),
        #: 为什么投给他。逐条可追溯，界面上直接用。
        sa.Column("why", sa.JSON, nullable=False, server_default="[]"),
        #: 排序位次。发起人那一屏按它排。
        sa.Column("rank", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("answered_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index(
        "ix_deliveries_inbox", "seed_deliveries", ["campus_id", "principal_id", "state"]
    )
    op.create_index("ix_deliveries_intent", "seed_deliveries", ["campus_id", "intent_id"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON seed_deliveries TO {APP_ROLE}")
    op.execute("ALTER TABLE seed_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE seed_deliveries FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY seed_deliveries_campus_isolation ON seed_deliveries
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.drop_table("seed_deliveries")
