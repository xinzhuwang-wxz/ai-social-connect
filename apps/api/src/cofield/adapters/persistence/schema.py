"""权威数据的表定义。

这里是 SQLAlchemy 的地盘——领域核心看不到它，也不该看到。
领域对象与行之间的转换写在各自的仓储适配器里，不用 ORM 映射，
这样"换掉持久化不触及领域测试"才是真的。
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

#: 会话级的租户变量。所有带 RLS 的表都按它过滤。
CAMPUS_SETTING = "app.current_campus"

#: 业务查询使用的角色。非属主、非超级用户、NOBYPASSRLS——这三条缺一，
#: 行级安全就形同虚设。见 migrations/versions/0001。
APP_ROLE = "cofield_app"

principals = sa.Table(
    "principals",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("display_name", sa.Text, nullable=False),
    # 合成主体标记。不只是测试便利——它承载一条治理要求：
    # 真人永远不应该以为自己在和真人配队。
    sa.Column(
        "is_synthetic",
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
    ),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
    ),
    sa.Index("ix_principals_campus", "campus_id"),
    sa.Index("ix_principals_campus_synthetic", "campus_id", "is_synthetic"),
)

#: 启用了行级隔离的表。迁移与测试都以这份清单为准，避免新表漏加策略。
RLS_TABLES: tuple[str, ...] = ("principals",)
