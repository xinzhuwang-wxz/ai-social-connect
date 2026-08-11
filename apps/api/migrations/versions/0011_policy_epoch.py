"""共域的策略纪元

场域智能体的能力令牌绑在这个计数器上。成员、提案、同意或策略一变就 +1，
所有旧令牌立刻失效。

为什么不是"给每张令牌设个短过期"就够：过期能挡住很久以前发的令牌，挡不住
三十秒前发的、而这三十秒里有人退出了。撤销必须是即时的，而唯一即时的撤销
手段是让所有旧令牌一起作废——一个单调计数器就够，不需要维护吊销名单。

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("policy_epoch", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("spaces", "policy_epoch")
