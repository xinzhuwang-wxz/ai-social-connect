"""行动机会：组织者发布的结构化供给。

冷启动策略是供给先行——没有人发布带席位的招募，撮合漏斗的第一段就是空的。
所以这不是一个"附加的组织者功能"，它是市场的一侧。

组织者角色是**事件级**的，不是全局身份：同一名学生可以在一个事件里是组织者，
在另一个事件里是普通参与者。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cofield.domain.model.principal import CampusId


@dataclass(frozen=True, slots=True)
class Organization:
    """社团、院系、实验室、赛事方。

    `verified` 不是装饰：学生要靠它判断这不是一个用来收集信息的假项目。
    未验证的组织不能发布招募。
    """

    id: UUID
    campus_id: CampusId
    name: str
    verified: bool = False


@dataclass(frozen=True, slots=True)
class Seat:
    """一类角色的席位。

    `filled` 由已确认的参与者数派生而来，不是一个可以随手改的计数器——
    它必须和真实成员数一致，否则缺口就是假的。
    """

    role: str
    capacity: int
    filled: int = 0

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("席位容量至少为 1")
        if self.filled < 0 or self.filled > self.capacity:
            raise ValueError("已占席位数超出容量")

    @property
    def gap(self) -> int:
        return self.capacity - self.filled

    @property
    def is_full(self) -> bool:
        return self.gap == 0


class OpportunityState:
    OPEN = "open"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ActionOpportunity:
    """一个带席位的招募。

    它必须有一个真人负责人（`steward_id`）。没有负责人的自动成局会导致
    责任分散——匿名聚合能降低发起压力，但没人承担下一步时事情就烂在那里。
    """

    id: UUID
    organization_id: UUID
    kind_key: str
    title: str
    goal: str
    seats: tuple[Seat, ...]
    steward_id: UUID
    deadline: datetime
    created_at: datetime
    #: 资格要求，例如"限大二以上""需要有过一次拍摄经历"。空表示不限。
    qualifications: tuple[str, ...] = ()
    location_scope: str | None = None
    state: str = OpportunityState.OPEN

    def __post_init__(self) -> None:
        if not self.seats:
            raise ValueError("招募必须至少有一个席位——否则学生不知道该来干什么")
        if self.deadline.tzinfo is None:
            raise ValueError("截止时间必须带时区")
        roles = [s.role for s in self.seats]
        if len(roles) != len(set(roles)):
            raise ValueError(f"席位角色重复：{roles}")

    @property
    def total_gap(self) -> int:
        return sum(s.gap for s in self.seats)

    @property
    def gaps(self) -> tuple[Seat, ...]:
        """还缺人的席位。组织者最关心这个，学生也是——他们要对着具体缺口来。"""
        return tuple(s for s in self.seats if not s.is_full)

    def is_open(self, *, now: datetime) -> bool:
        return (
            self.state == OpportunityState.OPEN
            and now < self.deadline
            and self.total_gap > 0
        )


def publishable(organization: Organization) -> tuple[bool, str | None]:
    """能不能发布招募。

    只有一条：组织必须经过验证。学生看到"已验证"才敢信这不是骗局，
    所以这条不能有例外。
    """
    if not organization.verified:
        return False, "未验证的组织不能发布招募"
    return True, None
