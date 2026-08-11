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
    #: 属于哪个行动类别。撮合窗口长度由它决定，所以它是真列不是 extras 里的键——
    #: 清算时要按它分组查询。可空：用户可以不挑场景直接写一句话。
    sa.Column("action_kind", sa.Text),
    #: 行动类别注册表声明的扩展字段。新增类别不改表结构。
    sa.Column("extras", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
    sa.Index("ix_intents_campus_state", "campus_id", "state"),
    # 撮合窗口按截止期排序取"即将离开市场"的人，这个索引服务那次查询。
    sa.Index("ix_intents_campus_deadline", "campus_id", "deadline"),
    sa.Index("ix_intents_principal", "campus_id", "principal_id"),
    # 清算按「市场单元」取人：同校园、同类别、还在等的。
    sa.Index("ix_intents_unit", "campus_id", "action_kind", "state"),
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

#: 窗口清算产出的成局提案。
#:
#: **它不是共同事件。** 提案只是"我们觉得这几个人能凑一队"，
#: 事件要等全员真人确认才诞生（见 #9 的确认门）。把两者放在同一张表里，
#: 迟早会有人拿提案当既成事实——所以它们分开，而且这张表里没有任何
#: 表示"已成局"的状态。
formation_proposals = sa.Table(
    "formation_proposals",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    #: 这个提案是回应谁的需求。
    sa.Column("intent_id", sa.Uuid, nullable=False),
    sa.Column("action_kind", sa.Text),
    #: 哪一次清算产出的。同一次清算的提案共享这个时刻——
    #: 它是"市场变厚"这件事的证据，也是复盘时的分组依据。
    sa.Column("cleared_at", sa.TIMESTAMP(timezone=True), nullable=False),
    #: 组员（含发起人）。顺序即求解器给出的顺序，发起人在首位。
    sa.Column("member_ids", PgArray(sa.Uuid), nullable=False),
    #: 成局证明的机器可读形态。界面上呈现的是它的转写，不是它的替代品——
    #: 申诉、A/B 与审计都读这个结构。
    sa.Column("proof", sa.JSON, nullable=False),
    #: 稳定性未通过的分区不得成为提案，所以这里恒为真。
    #: 仍然存下来，是为了让"这条不变量有没有被绕过"可被查询验证。
    sa.Column("stability_passed", sa.Boolean, nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    #: **实质条款的摘要。** 同意是对某一版条款的同意，不是对"这个提案"的
    #: 永久授权——人选、角色、时间、地点任何一项变了，之前那句"我加入"
    #: 就不再指向现在这件事。摘要变了旧承诺即失效，这是机器可判的，
    #: 不靠"记得去清空"。
    sa.Column("terms_digest", sa.Text, nullable=False, server_default=""),
    #: 第几版。条件接受（「我可以，但……」）会生成新版本。
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    #: 上一版。改条款是**新增一行**而不是改旧行——
    #: 谁在哪一版上答应过什么，申诉时要查得出来。
    sa.Column("supersedes", sa.Uuid),
    #: 被新版取代或被撤回的时刻。非空即不再接受新的答复。
    sa.Column("withdrawn_at", sa.TIMESTAMP(timezone=True)),
    sa.Index("ix_proposals_intent", "campus_id", "intent_id"),
    sa.Index("ix_proposals_cleared", "campus_id", "cleared_at"),
)


# --- 确认门与原子成局（#9）---

#: 每个人对一个提案的答复。
#:
#: 它是**唯一**能让事件诞生的东西。AI 可以代为表达，但不能代为承诺——
#: 所以这张表只接受真人签名的命令，没有任何自动写入的路径。
commitments = sa.Table(
    "commitments",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("proposal_id", sa.Uuid, nullable=False),
    sa.Column("principal_id", sa.Uuid, nullable=False),
    #: pending / accepted / declined / conditional
    #: `conditional` 是「我可以，但……」——它**不是**同意，
    #: 门槛不认它。少了这一档，想参与但有顾虑的人只能被迫二选一。
    sa.Column("state", sa.Text, nullable=False, server_default="pending"),
    #: 有条件接受时那句话的原文。系统不解析它，只把它带给别人看。
    sa.Column("condition", sa.Text),
    sa.Column("decided_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    # 一个人对一个提案只能有一条答复。改主意是改这一行，不是追加。
    sa.UniqueConstraint("proposal_id", "principal_id", name="uq_commitment_person"),
    sa.Index("ix_commitments_proposal", "campus_id", "proposal_id"),
    sa.Index("ix_commitments_principal", "campus_id", "principal_id"),
)

#: 共同事件。**全员确认之后才诞生，在一个事务里。**
#:
#: 达不到门槛什么都不产生——不是"先建一个草稿事件再慢慢凑人"。
#: 半成品事件会让参与者以为已经成了，而这正是这个产品最不该犯的错。
shared_events = sa.Table(
    "shared_events",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("proposal_id", sa.Uuid, nullable=False),
    sa.Column("action_kind", sa.Text),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("goal", sa.Text, nullable=False),
    # 必须有真人负责人：没有负责人的自动成局会导致责任分散。
    sa.Column("steward_id", sa.Uuid, nullable=False),
    sa.Column("formed_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("deadline", sa.TIMESTAMP(timezone=True)),
    #: active / completed / abandoned
    sa.Column("state", sa.Text, nullable=False, server_default="active"),
    # 一个提案最多变成一个事件。重复提交确认不该产生第二个。
    sa.UniqueConstraint("proposal_id", name="uq_event_per_proposal"),
    sa.Index("ix_events_campus_state", "campus_id", "state"),
)

event_members = sa.Table(
    "event_members",
    metadata,
    sa.Column("event_id", sa.Uuid, primary_key=True),
    sa.Column("principal_id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("role", sa.Text),
    sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False),
    #: 中途退出的人留在表里但标记时刻——关系边不能凭空消失，
    #: 否则「谁参加过什么」这件事就没有可信来源了。
    sa.Column("left_at", sa.TIMESTAMP(timezone=True)),
    sa.Index("ix_members_principal", "campus_id", "principal_id"),
)

# --- 共域（#10）---

#: 事件的空间。一个事件一个，不是群聊。
spaces = sa.Table(
    "spaces",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("event_id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    #: 助手开关。**关掉之后共域必须照常可用**——这是 M3 的判据之一。
    #: 助手是共域里的一张卡片，不是共域的运行时。
    sa.Column("agent_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    #: 策略纪元。成员、提案、同意或策略一变就 +1，**旧能力令牌立刻失效**。
    #:
    #: 为什么不是给每张令牌设短过期就够：过期能挡住"很久以前发的令牌"，
    #: 挡不住"三十秒前发的、但这三十秒里有人退出了"。撤销必须是即时的，
    #: 而唯一即时的撤销手段是让所有旧令牌一起作废——单调计数器就够，
    #: 不需要维护一张吊销名单。
    sa.Column("policy_epoch", sa.Integer, nullable=False, server_default="1"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.UniqueConstraint("event_id", name="uq_space_per_event"),
    sa.Index("ix_spaces_campus", "campus_id"),
)

#: 共域里的一条东西：任务、素材、决策门、记录。
#:
#: 用 `kind` 区分而不是四张表——新增一种条目应该是新增一条声明，
#: 不是新增一张表加一套 CRUD。这和行动类别注册表是同一个扩展点思路。
space_items = sa.Table(
    "space_items",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("space_id", sa.Uuid, nullable=False),
    #: task / material / decision_gate / note
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("title", sa.Text, nullable=False),
    sa.Column("body", sa.Text),
    #: 各 kind 自己的状态：任务是 todo/doing/done，决策门是 open/settled。
    sa.Column("state", sa.Text, nullable=False, server_default="open"),
    sa.Column("assignee_id", sa.Uuid),
    sa.Column("due_at", sa.TIMESTAMP(timezone=True)),
    #: 是不是助手起草的。**必须能看出来**——AI 起草、人类决定，
    #: 分不清谁写的，"人类决定"就只是一句话。
    sa.Column("drafted_by_agent", sa.Boolean, nullable=False, server_default=sa.false()),
    #: 助手起草的东西在被真人采纳之前不算数。
    sa.Column("accepted_by", sa.Uuid),
    sa.Column("created_by", sa.Uuid, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("extras", sa.JSON, nullable=False, server_default="{}"),
    sa.Index("ix_items_space_kind", "campus_id", "space_id", "kind"),
)

# --- 受限协商（#8）---

#: 一次协商，持久化的是 A2A 的 Task 生命周期（见 ADR 0004）。
#:
#: 复用它是因为 A2A 有两个**非终止的中断态**——`INPUT_REQUIRED` 与
#: `AUTH_REQUIRED`——语义正是"交还给真人"。自研一个语义相同的状态机
#: 既是重复造轮子，也会让将来接第三方个人代理时多一层翻译。
negotiation_tasks = sa.Table(
    "negotiation_tasks",
    metadata,
    #: A2A 的 taskId。用文本而不是 UUID：协议里它是字符串，
    #: 将来对接外部代理时不该由我们规定它长什么样。
    sa.Column("task_id", sa.Text, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    #: A2A 的 contextId。同一次成局的多轮协商共享它。
    sa.Column("context_id", sa.Text, nullable=False),
    sa.Column("proposal_id", sa.Uuid, nullable=False),
    #: A2A TaskState 的取值，原样存，不翻译成我们自己的词。
    sa.Column("state", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_negotiation_proposal", "campus_id", "proposal_id"),
    sa.Index("ix_negotiation_context", "campus_id", "context_id"),
)

#: 协商里的一条消息。**七种受限类型，没有一种构成同意。**
#:
#: 自由格式协商是攻击面：实证显示 agent 易受提示注入，且选择过载与
#: 首提案偏差会让"回得快"打败"最合适"。所以消息是结构化载荷，
#: 装在 A2A 的 `Message.parts` 里，不是另一套协议。
negotiation_messages = sa.Table(
    "negotiation_messages",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("campus_id", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text, nullable=False),
    sa.Column("author_id", sa.Uuid, nullable=False),
    #: A2A 的 Message.role：user / agent。作者是人还是 agent
    #: 在协议层就有位置，不需要另加字段。
    sa.Column("role", sa.Text, nullable=False),
    #: 七种受限消息类型之一。
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("payload", sa.JSON, nullable=False),
    #: 代聊三档：本人 / AI 起草本人过目 / AI 代答。
    #: 是否向对方披露由行动类别注册表的 `agent_reply_policy` 决定，
    #: 是可配置策略不是不变量——但**记录下来是不变量**，
    #: 申诉时要能查出这句话到底是谁说的。
    sa.Column("speaker_mode", sa.Text, nullable=False, server_default="self"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Index("ix_messages_task", "campus_id", "task_id", "created_at"),
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
    "formation_proposals",
    "commitments",
    "shared_events",
    "event_members",
    "spaces",
    "space_items",
    "negotiation_tasks",
    "negotiation_messages",
)
