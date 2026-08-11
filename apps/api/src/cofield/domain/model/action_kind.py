"""行动类别注册表。

场景差异全部落在这里，不落在代码分支里。新增一个类别是新增一条声明，
**不改领域核心的任何一个文件**——这条由回归测试守着。

一条声明同时决定了：首屏出现什么卡、意图多了哪些字段、硬约束加什么、
席位怎么排、风险层级多高、地点能显示多细、撮合窗口多长、代聊是否披露。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum


class RiskTier(StrEnum):
    """风险层级决定安全控制强度。见 04-治理与安全 §3。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlacePrecision(StrEnum):
    """对外可显示的最细地点粒度。服务端强制降精度后再输出。"""

    BUILDING = "building"
    ZONE = "zone"
    CAMPUS = "campus"
    NONE = "none"


class AgentReplyPolicy(StrEnum):
    """AI 代答是否向对方披露。可配置策略，不是领域不变量。"""

    ALWAYS_DISCLOSE = "always_disclose"
    DISCLOSE_ON_SENSITIVE = "disclose_on_sensitive"
    NO_DISCLOSE = "no_disclose"


@dataclass(frozen=True, slots=True)
class StarterCard:
    """首屏的场景引子。

    `example` 是一句**完整的好例子**，不是"请输入…"。它同时起示范作用，
    告诉用户什么样的表达能被接住——冷启动用户面对空输入框会卡住，
    这是漏斗第一段最大的流失点。
    """

    title: str
    example: str


@dataclass(frozen=True, slots=True)
class SeatModel:
    roles: tuple[str, ...]
    minimum: int
    maximum: int


@dataclass(frozen=True, slots=True)
class ActionKind:
    key: str
    label: str
    starter: StarterCard
    seat_model: SeatModel
    risk_tier: RiskTier = RiskTier.LOW
    place_precision: PlacePrecision = PlacePrecision.BUILDING
    agent_reply_policy: AgentReplyPolicy = AgentReplyPolicy.ALWAYS_DISCLOSE
    #: 撮合窗口长度。截止期临近的成员会被单独提前清算，不必等窗口。
    matching_window: timedelta = timedelta(hours=6)
    #: 该类别在基础意图 schema 之上追加的字段名。
    intent_schema_ext: tuple[str, ...] = ()
    #: 行动回声期望的证据类型。
    echo_template: tuple[str, ...] = ()
    extra_hard_constraints: tuple[str, ...] = field(default_factory=tuple)


class ActionKindRegistry:
    """按 key 查类别。找不到时明确报错，不静默回退到某个默认值——
    静默回退会让"新场景没注册"这种错误一直藏到线上。"""

    def __init__(self, kinds: tuple[ActionKind, ...]) -> None:
        duplicates = {k.key for k in kinds if [x.key for x in kinds].count(k.key) > 1}
        if duplicates:
            raise ValueError(f"行动类别 key 重复：{sorted(duplicates)}")
        self._by_key = {k.key: k for k in kinds}

    def __len__(self) -> int:
        return len(self._by_key)

    def all(self) -> tuple[ActionKind, ...]:
        return tuple(self._by_key.values())

    def get(self, key: str) -> ActionKind:
        try:
            return self._by_key[key]
        except KeyError:
            raise KeyError(
                f"未注册的行动类别：{key}。可用：{sorted(self._by_key)}"
            ) from None

    def starters(self) -> tuple[StarterCard, ...]:
        return tuple(k.starter for k in self._by_key.values())
