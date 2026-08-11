"""匹配信封与同意记录。

用户在任何人看到自己之前，逐项决定这次露出什么。每一项都带**用途、
接收范围、有效期**——这三样缺一，"最小披露"就只是一句口号。

同意记录的结构照搬 ISO/IEC TS 27560:2023（以 Kantara Consent Receipt v1.1
为基础）。既然开源复用是红线，标准复用同理——自创同意 schema 属于
重复造轮子。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Audience(StrEnum):
    """这一项给谁看。

    `SOLVER_ONLY` 是关键档位：字段参与求解但不出现在任何对外输出里。
    没有它，用户就只能在"完全不给"和"给所有人看"之间二选一。
    """

    SOLVER_ONLY = "solver_only"
    CANDIDATES = "candidates"


class Purpose(StrEnum):
    """用途绑定。令牌只能在声明的用途下使用。"""

    FORMATION_FEASIBILITY = "formation_feasibility"
    FORMATION_PROOF = "formation_proof"


#: 可以被逐项授权的字段。**白名单**——没列在这里的字段一律不可外发，
#: 新增字段必须显式加入并说明用途，不能靠"忘了排除"就漏出去。
GRANTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "goal",
        "offers",
        "needs",
        "time_window",
        "location_scope",
        "team_size",
        "boundaries",
        "open_questions",
        "portfolio_link",
        # 自己写的一段话。它进语义索引，所以**必须**可被逐项授权与撤回——
        # 撤回时连带删掉索引行，否则原话会继续参与别人的匹配。
        "self_intro",
        # --- 属于「人」而不是「这次需求」的两项 ---
        # 上面那些换一条需求就换一套；下面这两项换多少条需求都是同一份。
        # 混在一个白名单里看不出来，所以在这里标出来（并见 http/envelopes.PRINCIPAL_SCOPED）。
        #
        # 已确认完成的事件数。**闭环靠它合上**：没有它，成局证明就永远说不出
        # 「他有两次已确认的短片交付记录」（02 §5.1 的设计示例），
        # 而「记录改变下一次成局证明」这条 M4 判据也就无从谈起。
        "confirmed_events",
        # 专业。CROSS_MAJOR 是软目标，证明想说「你们三个不同专业」就得引用它。
        # 它同时也是敏感信息，所以是**授权项**不是公开字段。
        "major",
    }
)

#: 刻意**不**放进白名单的属性，以及为什么。
#:
#: `active_commitments`（当前并发承诺数）——它是求解侧的硬约束（CONCURRENCY），
#: 但说出口就变了味：「他手上已经有三件事」会被读成一个负面判断，
#: 而且没有人会主动选择公布自己有多忙。参与求解可以，出现在证明里不行。
#: 这正是 `Audience.SOLVER_ONLY` 那一档存在的理由——但它连那一档都不该有，
#: 因为它根本不是用户填的，是系统数出来的。
DELIBERATELY_UNGRANTABLE: frozenset[str] = frozenset({"active_commitments"})


@dataclass(frozen=True, slots=True)
class FieldGrant:
    """一个字段的授权。"""

    field_name: str
    audience: Audience
    purposes: frozenset[Purpose]

    def __post_init__(self) -> None:
        if self.field_name not in GRANTABLE_FIELDS:
            raise ValueError(
                f"{self.field_name} 不在可授权字段白名单里——"
                f"新字段要显式加入并说明用途"
            )
        if not self.purposes:
            raise ValueError("授权必须绑定用途")

    def permits(self, *, audience: Audience, purpose: Purpose) -> bool:
        if purpose not in self.purposes:
            return False
        if audience is Audience.CANDIDATES:
            return self.audience is Audience.CANDIDATES
        return True


class EnvelopeState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class MatchEnvelope:
    """一次匹配里允许使用与披露的信息集合。

    它不是"用户档案的一个视图"——它是**一次授权**，有有效期，可撤销，
    撤销之后新请求立刻被拒。
    """

    id: UUID
    principal_id: UUID
    intent_id: UUID
    grants: tuple[FieldGrant, ...]
    created_at: datetime
    expires_at: datetime
    state: EnvelopeState = EnvelopeState.ACTIVE
    #: 允许本次引用的记忆切面。留空表示"只用这次说的话去配队"。
    cited_facet_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        names = [g.field_name for g in self.grants]
        if len(names) != len(set(names)):
            raise ValueError(f"同一字段被授权了多次：{names}")

    def is_usable(self, *, now: datetime) -> bool:
        return self.state is EnvelopeState.ACTIVE and now < self.expires_at

    def revoke(self) -> MatchEnvelope:
        return replace(self, state=EnvelopeState.REVOKED)

    def visible_fields(
        self, *, audience: Audience, purpose: Purpose, now: datetime
    ) -> frozenset[str]:
        """在给定受众与用途下，允许出现的字段名。

        信封失效时返回空集——**默认拒绝**。调用方拿到空集就什么都发不出去，
        而不是"忘了检查就全发"。
        """
        if not self.is_usable(now=now):
            return frozenset()
        return frozenset(
            g.field_name
            for g in self.grants
            if g.permits(audience=audience, purpose=purpose)
        )


class ConsentEventKind(StrEnum):
    GIVEN = "given"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class ConsentEvent:
    kind: ConsentEventKind
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    """同意记录，字段结构对齐 ISO/IEC TS 27560:2023。

    与 `MatchEnvelope` 的分工：信封是**运行期用来过滤字段的对象**，
    同意记录是**可审计的事实**。前者会被撤销和过期，后者永远追加不修改——
    申诉和导出时看的是后者。
    """

    # Header
    record_id: UUID
    created_at: datetime

    # PII Principal / Controller
    pii_principal_id: UUID

    schema_version: str = "ISO/IEC TS 27560:2023"
    pii_controller: str = "共域 CoField"

    # Privacy notice
    notice_reference: str = "docs/04-治理与安全.md"

    # PII Processing
    purposes: tuple[Purpose, ...] = ()
    pii_categories: tuple[str, ...] = ()
    audience: Audience = Audience.SOLVER_ONLY
    retention_until: datetime | None = None

    # Events：只追加，不修改。撤销是追加一条 withdrawn，不是改写 given。
    events: tuple[ConsentEvent, ...] = ()
