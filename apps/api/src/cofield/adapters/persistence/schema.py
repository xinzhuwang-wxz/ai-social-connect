"""权威数据的表定义。

这里是 SQLAlchemy 的地盘——领域核心看不到它，也不该看到。
领域对象与行之间的转换写在各自的仓储适配器里，不用 ORM 映射，
这样"换掉持久化不触及领域测试"才是真的。
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY as PgArray

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
    # --- 漏斗第一段用来做 SQL 硬过滤的列 ---
    # 它们不是"合成人口专用"：真实用户同样有技能、空闲和校区。
    sa.Column("major", sa.Text),
    sa.Column("year", sa.Integer),
    sa.Column("zone", sa.Text),
    # 用方言 ARRAY 而不是通用 ARRAY：硬过滤要用 `&&` 重叠运算符，
    # 通用类型没有这个比较器。生成的 DDL 相同。
    sa.Column("skills", PgArray(sa.Text), nullable=False, server_default="{}"),
    #: 21 位周课表掩码（7 天 × 上午/下午/晚上），1 表示有空。
    #: 整组共同空闲 = 按位与。真正咬人的约束是"连续两段"而不是"任意一段"。
    sa.Column("availability", sa.Text),
    #: 自己写的一段话。它**故意不被结构化**——"想找个写朋克风格文案的"
    #: 这类需求没有字段接得住，只能靠这段原话进语义索引。
    #: 它是可授权字段（见 consent.GRANTABLE_FIELDS），不是默认公开。
    sa.Column("self_intro", sa.Text),
    sa.Index("ix_principals_campus", "campus_id"),
    sa.Index("ix_principals_campus_synthetic", "campus_id", "is_synthetic"),
    sa.Index("ix_principals_skills", "skills", postgresql_using="gin"),
    sa.Index("ix_principals_campus_zone", "campus_id", "zone"),
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

match_envelopes = sa.Table(
    "match_envelopes",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("principal_id", sa.Uuid, nullable=False),
    sa.Column("intent_id", sa.Uuid, nullable=False),
    # 逐项授权：字段 → {audience, purposes}。白名单在领域层强制。
    sa.Column("grants", sa.JSON, nullable=False),
    sa.Column("cited_facet_ids", sa.ARRAY(sa.Uuid), nullable=False, server_default="{}"),
    sa.Column("state", sa.Text, nullable=False, server_default="active"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_envelopes_intent", "campus_id", "intent_id"),
    sa.Index("ix_envelopes_principal", "campus_id", "principal_id"),
)

consent_records = sa.Table(
    "consent_records",
    metadata,
    # 结构对齐 ISO/IEC TS 27560:2023。**只追加不修改**——撤销是追加一条
    # withdrawn 事件，不是改写原记录。申诉与导出看的是这张表。
    sa.Column("record_id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("pii_principal_id", sa.Uuid, nullable=False),
    sa.Column("pii_controller", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False),
    sa.Column("notice_reference", sa.Text, nullable=False),
    sa.Column("purposes", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("pii_categories", sa.ARRAY(sa.Text), nullable=False),
    sa.Column("audience", sa.Text, nullable=False),
    sa.Column("retention_until", sa.TIMESTAMP(timezone=True)),
    sa.Column("events", sa.JSON, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_consent_principal", "campus_id", "pii_principal_id"),
)

#: 语义索引的维度。与 Embedder 端口声明的维度必须一致。
EMBEDDING_DIMENSIONS = 384

#: 语义召回索引。
#:
#: 只索引**已授权用于匹配**的内容——未授权的原话不进这张表，
#: 撤销授权即删行。向量是派生物，删库能从权威事实重建。
#:
#: 它承载的是 schema 装不下的那部分表达：「想找个写朋克风格文案的」
#: 没有任何结构化字段能装，但原话里有。
semantic_index = sa.Table(
    "semantic_index",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    #: 被索引对象的类型与主键。目前是 principal 的自述与 intent 的原话。
    sa.Column("subject_kind", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Uuid, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
    sa.Column("model", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.UniqueConstraint("subject_kind", "subject_id", name="uq_semantic_subject"),
    sa.Index("ix_semantic_campus_kind", "campus_id", "subject_kind"),
)

#: 启用了行级隔离的表。迁移与测试都以这份清单为准，避免新表漏加策略。
RLS_TABLES: tuple[str, ...] = (
    "principals",
    "intent_signals",
    "organizations",
    "action_opportunities",
    "opportunity_seats",
    "match_envelopes",
    "consent_records",
    "semantic_index",
)
