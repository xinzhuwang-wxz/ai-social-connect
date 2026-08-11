"""成局求解的共享契约。

求解、稳定性检查、成局证明三者各自独立，只通过这里的类型通信。
它们都是**纯函数**：不碰数据库、不碰 schema、不碰路由——所以可以并行开发，
也所以换掉任何一个都不触及其余两个的测试。

编码在这些类型里的产品判断：

- 求解对象是**一个组**，不是一对人（`CandidateGroup` 而不是 `Pair`）
- 硬约束是**过滤器**（`HardConstraint` 与 `Objective` 分开放），任何软分
  都不能抵消一条硬约束冲突
- 稳定性是**门**不是分（`StabilityVerdict.passed` 是布尔，不是权重）
- 证明是**机器可读结构**（`FormationProof` 里全是结构化条目），LLM 只做转写
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

WEEK_SLOTS = 21


# --- 输入 -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Member:
    """参与求解的一个人。

    `availability` 是 21 位周掩码。整组共同空闲 = 按位与——实测表明真正咬人的
    约束是「整组连续两段共同空闲」（4 人组 50%，5 人组 27%），不是「任意一段」。
    """

    principal_id: UUID
    display_name: str
    skills: frozenset[str]
    availability: str
    zone: str | None = None
    major: str | None = None
    #: 该成员已确认完成的事件数。用于「可核验」而非「分数更高」——
    #: 它只影响证明里能引用什么，不直接加分。
    confirmed_events: int = 0
    #: 当前并发承诺数。超过上限的人不该被再塞进新组。
    active_commitments: int = 0
    #: 最近被提案的次数。用于曝光公平，避免提案全集中到少数热门候选。
    recent_exposure: int = 0


@dataclass(frozen=True, slots=True)
class Requirement:
    """一次成局要满足什么。"""

    intent_id: UUID
    requester: Member
    goal: str
    needs: tuple[str, ...]
    team_min: int
    team_max: int
    deadline: datetime
    zone: str | None = None
    #: 需要整组共同空闲的连续段数。
    contiguous_slots: int = 2
    #: 每人最多同时参与几个共同事件。
    max_concurrent: int = 3
    excluded: frozenset[UUID] = frozenset()


class ConstraintKind(StrEnum):
    ROLE_COVERAGE = "role_coverage"
    TEAM_SIZE = "team_size"
    COMMON_TIME = "common_time"
    ZONE = "zone"
    CONCURRENCY = "concurrency"
    EXCLUSION = "exclusion"


@dataclass(frozen=True, slots=True)
class HardConstraint:
    """必须满足。**不参与打分**——任何软分都不能抵消一条冲突。"""

    kind: ConstraintKind
    detail: str


class ObjectiveKind(StrEnum):
    ROLE_FIT = "role_fit"
    RECIPROCITY = "reciprocity"
    TIME_SLACK = "time_slack"
    CROSS_MAJOR = "cross_major"
    EXPOSURE_FAIRNESS = "exposure_fairness"
    NEWCOMER_PROTECTION = "newcomer_protection"


@dataclass(frozen=True, slots=True)
class Objective:
    """软目标。每一项必须能独立解释——不可解释的项不许加进来。"""

    kind: ObjectiveKind
    weight: float


DEFAULT_OBJECTIVES: tuple[Objective, ...] = (
    Objective(ObjectiveKind.ROLE_FIT, 3.0),
    Objective(ObjectiveKind.RECIPROCITY, 2.0),
    Objective(ObjectiveKind.TIME_SLACK, 1.5),
    Objective(ObjectiveKind.CROSS_MAJOR, 0.8),
    # 负权重：被反复提案的人要降权，避免所有提案集中到少数热门候选。
    Objective(ObjectiveKind.EXPOSURE_FAIRNESS, -1.0),
    # 零历史的人不该因为缺历史而系统性吃亏。
    Objective(ObjectiveKind.NEWCOMER_PROTECTION, 0.5),
)


@dataclass(frozen=True, slots=True)
class SolveRequest:
    requirement: Requirement
    candidates: tuple[Member, ...]
    objectives: tuple[Objective, ...] = DEFAULT_OBJECTIVES
    #: 要几个互不相同的候选组。产出给用户的只有 2–3 个：实证表明选择变多
    #: 反而降低决策质量（搜索上限 3→100 时福利下降）。多出来的用于稳定性比较。
    group_count: int = 6
    #: 求可行解的秒数，与改进目标的秒数。
    feasible_seconds: float = 2.0
    improve_seconds: float = 8.0


# --- 输出 -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObjectiveContribution:
    """某个目标项贡献了多少。证明里逐条引用它，不给总分。"""

    kind: ObjectiveKind
    raw: float
    weighted: float
    explanation: str


@dataclass(frozen=True, slots=True)
class CandidateGroup:
    members: tuple[Member, ...]
    #: 每个缺口由谁补。证明里「为什么是这几个人」直接用它。
    role_assignment: dict[str, UUID]
    #: 整组共同空闲的连续段起始位置。
    common_slots: tuple[int, ...]
    contributions: tuple[ObjectiveContribution, ...]
    score: float

    @property
    def member_ids(self) -> frozenset[UUID]:
        return frozenset(m.principal_id for m in self.members)


@dataclass(frozen=True, slots=True)
class SolveResult:
    groups: tuple[CandidateGroup, ...]
    #: 无解时说明是哪些硬约束共同导致的。不伪造候选。
    blocked_by: tuple[HardConstraint, ...] = ()
    solver_status: str = "unknown"
    elapsed_seconds: float = 0.0


# --- 稳定性 -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Defection:
    """一个成员更想去的别的组。"""

    principal_id: UUID
    prefers_group_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class StabilityVerdict:
    """稳定性是**门**不是分。

    求解器算出的最优分区未必稳定——被塞进不喜欢的组的人会在第一次线下见面前
    退出，整组随之崩掉。未通过的分区不得提交为提案。
    """

    passed: bool
    defections: tuple[Defection, ...] = ()
    #: 给人看的一句话。通过时是那句可证伪的承诺。
    statement: str = ""


# --- 成局证明 ---------------------------------------------------------------


class EvidenceSource(StrEnum):
    """证明里每条理由的来源。只允许这五种——LLM 不得发明第六种。"""

    USER_STATEMENT = "user_statement"
    APPROVED_FACET = "approved_facet"
    SOLVER_CONSTRAINT = "solver_constraint"
    OBJECTIVE_CONTRIBUTION = "objective_contribution"
    UNRESOLVED_CONFLICT = "unresolved_conflict"


@dataclass(frozen=True, slots=True)
class ProofLine:
    source: EvidenceSource
    text: str
    #: 可追溯到的对象。空表示这条来自本次用户表达。
    refers_to: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormationProof:
    """机器可读的成局证明。

    界面上呈现的是它的转写，**不是**它的替代品——审计、A/B 与申诉都读这个结构。
    禁止出现总分或百分比。
    """

    satisfied: tuple[ProofLine, ...]
    #: 必须由真人决定的事。它们不是缺失项，是**刻意留给人**的。
    for_humans: tuple[ProofLine, ...]
    #: 系统自己承认的不确定。藏起来比说出来伤害大。
    uncertainties: tuple[ProofLine, ...] = ()
    stability: StabilityVerdict | None = None
    expires_at: datetime | None = None
    generated_at: datetime | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
