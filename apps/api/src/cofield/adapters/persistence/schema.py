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

intent_signals = sa.Table(
    "intent_signals",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("principal_id", sa.Uuid, nullable=False),
    sa.Column("state", sa.Text, nullable=False),
    # 用户说的原话永远保留：抽取错了能追溯，也能拿去改进抽取器。
    sa.Column("raw_expression", sa.Text, nullable=False),
    sa.Column("goal", sa.Text, nullable=False),
    # 硬约束提升为真列而不是塞进 JSONB——漏斗第一段要用 SQL 过滤它们，
    # 而且它们要建索引。可扩展的部分放 extras。
    sa.Column("earliest", sa.TIMESTAMP(timezone=True)),
    sa.Column("deadline", sa.TIMESTAMP(timezone=True)),
    sa.Column("location_scope", sa.Text),
    sa.Column("team_min", sa.Integer),
    sa.Column("team_max", sa.Integer),
    sa.Column("offers", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    sa.Column("needs", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    sa.Column("boundaries", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    sa.Column("open_questions", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    sa.Column("uncertain_fields", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    #: 行动类别注册表声明的扩展字段。新增类别不改表结构。
    sa.Column("extras", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
    sa.Index("ix_intents_campus_state", "campus_id", "state"),
    # 撮合窗口按截止期排序取"即将离开市场"的人，这个索引服务那次查询。
    sa.Index("ix_intents_campus_deadline", "campus_id", "deadline"),
    sa.Index("ix_intents_principal", "campus_id", "principal_id"),
)

organizations = sa.Table(
    "organizations",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    # 学生要靠它判断这不是一个用来收集信息的假项目。未验证不能发布招募。
    sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_orgs_campus", "campus_id"),
)

action_opportunities = sa.Table(
    "action_opportunities",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("organization_id", sa.Uuid, nullable=False),
    sa.Column("kind_key", sa.Text, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("goal", sa.Text, nullable=False),
    # 必须有真人负责人：没有负责人的自动成局会导致责任分散。
    sa.Column("steward_id", sa.Uuid, nullable=False),
    sa.Column("deadline", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("location_scope", sa.Text),
    sa.Column("qualifications", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
    sa.Column("state", sa.Text, nullable=False, server_default="open"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_opps_campus_state", "campus_id", "state"),
    sa.Index("ix_opps_campus_deadline", "campus_id", "deadline"),
)

opportunity_seats = sa.Table(
    "opportunity_seats",
    metadata,
    sa.Column("opportunity_id", sa.Uuid, primary_key=True),
    sa.Column("role", sa.Text, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("capacity", sa.Integer, nullable=False),
    # 已占席位。它必须和真实成员数一致，否则缺口就是假的。
    sa.Column("filled", sa.Integer, nullable=False, server_default="0"),
)

#: 启用了行级隔离的表。迁移与测试都以这份清单为准，避免新表漏加策略。
RLS_TABLES: tuple[str, ...] = (
    "principals",
    "intent_signals",
    "organizations",
    "action_opportunities",
    "opportunity_seats",
)
