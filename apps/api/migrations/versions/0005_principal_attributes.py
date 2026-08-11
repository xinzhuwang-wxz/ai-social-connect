"""主体的可过滤属性

技能、空闲、校区提升为真列并建索引：漏斗第一段是 SQL 硬过滤，
它要在两万人上跑得动。

`availability` 是 21 位周掩码。整组共同空闲用按位与算——实测表明真正
咬人的约束是「整组有连续两段共同空闲」（4 人组只有 50% 能凑上），
而不是「有任意一段重合」（几乎总能凑上）。

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("principals", sa.Column("major", sa.Text))
    op.add_column("principals", sa.Column("year", sa.Integer))
    op.add_column("principals", sa.Column("zone", sa.Text))
    op.add_column(
        "principals",
        sa.Column("skills", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    )
    op.add_column("principals", sa.Column("availability", sa.Text))
    op.create_index(
        "ix_principals_skills", "principals", ["skills"], postgresql_using="gin"
    )
    op.create_index("ix_principals_campus_zone", "principals", ["campus_id", "zone"])


def downgrade() -> None:
    op.drop_index("ix_principals_campus_zone", table_name="principals")
    op.drop_index("ix_principals_skills", table_name="principals")
    for column in ("availability", "skills", "zone", "year", "major"):
        op.drop_column("principals", column)
