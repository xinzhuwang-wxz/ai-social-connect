"""意图信号：用户此刻想和别人一起完成什么。

意图不是画像的降级版，是另一类对象。画像回答"我是谁"，需要积累；
意图回答"我现在想和谁一起做什么"，六十秒能说完。冷启动之所以成立，
就是因为意图本身就是完整信息。

生命周期：

    stashed → draft → consented → active → matched | withdrawn | expired

`stashed` 是"还没想清楚的一句念头"：只对本人可见、不参与撮合、无过期压力。
`draft` 是抽取结果，**未经用户确认，不得进入撮合的任何一段**。
只有 `active` 参与撮合。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class IntentState(StrEnum):
    STASHED = "stashed"
    DRAFT = "draft"
    CONSENTED = "consented"
    ACTIVE = "active"
    MATCHED = "matched"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


#: 参与撮合的状态。别处一律以这个集合为准，不要各自写 `== ACTIVE`。
MATCHABLE_STATES: frozenset[IntentState] = frozenset({IntentState.ACTIVE})


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """行动的时间范围。`deadline` 同时是用户退出市场的时刻——撮合窗口靠它排序。"""

    earliest: datetime
    deadline: datetime

    def __post_init__(self) -> None:
        for label, value in (("earliest", self.earliest), ("deadline", self.deadline)):
            if value.tzinfo is None:
                raise ValueError(f"{label} 必须带时区")
        if self.deadline < self.earliest:
            raise ValueError("截止时间不能早于开始时间")


@dataclass(frozen=True, slots=True)
class TeamSize:
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if self.minimum < 2:
            raise ValueError("共同事件至少两个人——一个人做的事不需要这个产品")
        if self.maximum < self.minimum:
            raise ValueError("团队人数上限不能小于下限")


@dataclass(frozen=True, slots=True)
class Conflict:
    """硬约束之间的矛盾。指出是哪两条打架，而不是泛泛地说"输入有误"。"""

    field: str
    detail: str


@dataclass(frozen=True, slots=True)
class IntentContent:
    """一次意图的实质内容。抽取产出它，用户修改它，撮合读它。"""

    goal: str
    offers: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    time_window: TimeWindow | None = None
    location_scope: str | None = None
    team_size: TeamSize | None = None
    boundaries: tuple[str, ...] = ()
    #: 用户自己也还没定的事（是否公开、署名规则……）。它们不是缺失字段，
    #: 而是**要留给真人在成局时决定**的事项，会原样进入成局证明。
    open_questions: tuple[str, ...] = ()
    #: 抽取器标注的低置信字段名。界面据此提示用户重点核对。
    uncertain_fields: frozenset[str] = field(default_factory=frozenset)

    def conflicts(self, *, now: datetime) -> tuple[Conflict, ...]:
        """自相矛盾检查。返回全部冲突，不是遇到第一个就停——用户想一次改完。"""
        found: list[Conflict] = []

        if not self.goal.strip():
            found.append(Conflict("goal", "没说要做什么"))

        if self.time_window is not None and self.time_window.deadline < now:
            found.append(
                Conflict("time_window", "截止时间已经过去了，现在配队也来不及")
            )

        if self.team_size is not None and self.needs:
            # 需要 N 个角色，团队上限却装不下这些人加自己
            required = len(self.needs) + 1
            if self.team_size.maximum < required:
                found.append(
                    Conflict(
                        "team_size",
                        f"你缺 {len(self.needs)} 个角色，加上自己至少 {required} 人，"
                        f"但团队上限写的是 {self.team_size.maximum}",
                    )
                )

        overlap = set(self.offers) & set(self.needs)
        if overlap:
            found.append(
                Conflict("needs", f"这些既写在能提供里又写在需要里：{sorted(overlap)}")
            )

        return tuple(found)


@dataclass(frozen=True, slots=True)
class IntentSignal:
    """一条意图。

    `raw_expression` 与结构化内容并存——用户说的原话永远保留，
    这样抽取错了能追溯，也能拿去改进抽取器。
    """

    id: UUID
    principal_id: UUID
    state: IntentState
    raw_expression: str
    content: IntentContent
    created_at: datetime
    expires_at: datetime | None = None

    @property
    def is_matchable(self) -> bool:
        return self.state in MATCHABLE_STATES

    def is_expired(self, *, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def revise(self, content: IntentContent) -> IntentSignal:
        """用户改了内容。改动之后仍需重新确认——所以回到 draft。"""
        if self.state in {IntentState.MATCHED, IntentState.WITHDRAWN}:
            raise ValueError(f"{self.state} 的意图不能再修改")
        return replace(self, content=content, state=IntentState.DRAFT)

    def confirm(self, *, now: datetime, ttl: timedelta) -> IntentSignal:
        """用户确认结构化结果无误。这是"未经确认不得进入撮合"的那道门。"""
        conflicts = self.content.conflicts(now=now)
        if conflicts:
            raise ValueError(f"还有冲突没解决：{[c.detail for c in conflicts]}")
        if self.state not in {IntentState.STASHED, IntentState.DRAFT}:
            raise ValueError(f"{self.state} 的意图不需要再确认")
        return replace(
            self,
            state=IntentState.ACTIVE,
            expires_at=_earliest_expiry(now + ttl, self.content.time_window),
        )

    def withdraw(self) -> IntentSignal:
        return replace(self, state=IntentState.WITHDRAWN)


def _earliest_expiry(ttl_expiry: datetime, window: TimeWindow | None) -> datetime:
    """意图不该活过它自己的截止时间——那之后再配上也没意义。"""
    if window is None:
        return ttl_expiry
    return min(ttl_expiry, window.deadline)
