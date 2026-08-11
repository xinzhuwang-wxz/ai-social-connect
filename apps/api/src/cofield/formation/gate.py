"""确认门：达不到门槛就什么都不产生。

## 这一层承载三条不可越过的约束里的两条

> 未获真人确认的提案不创建事件、共域或关系边
> AI 可以代为表达，但不能代为承诺

所以这里没有任何"自动通过"的路径，一条都没有。承诺只能由带真人身份的
命令写入，而事件、成员关系、共域三者要么一起诞生，要么一个都不诞生。

## 为什么必须是原子的

半成品最伤人。如果先建一个"草稿事件"再慢慢凑人，参与者会以为已经成了——
他会去排时间、去准备、去跟别人说。等到发现没凑齐，损失的不是一次匹配，
是一次信任。**宁可什么都没有，不要一个像成了的东西。**

## 同意是对某一版条款的同意

不是对"这个提案"的永久授权。人选、角色、时间、地点任何一项变了，
之前那句「我加入」就不再指向现在这件事——`terms_digest` 让这件事
机器可判，不靠"记得去清空承诺表"。

## 「我可以，但……」不是同意

`CONDITIONAL` 是独立的一档，门槛**不认它**。

少了这一档，想参与但有顾虑的人只能在"违心答应"和"直接拒绝"之间二选一，
而这两种结果对所有人都更差。有条件接受会生成新一版条款，受影响的成员
重新确认——这就是它比"先答应再说"好的地方：顾虑被写进条款，不是被咽下去。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

#: 提案发出后，成员有多久做决定。
#:
#: 太短会逼人仓促答应，太长会让先答应的人一直悬着——而"一直悬着"正是
#: 最容易让人干脆不回的状态。真正的上限还要和提案本身的失效时刻取较早者。
DECISION_WINDOW = timedelta(hours=36)


class CommitmentState(StrEnum):
    """一个人对一版条款的答复。"""

    #: 还没回。**不是拒绝**——没回和拒绝在产品上是两件事，
    #: 混起来会让"还在等谁"这一屏说不出话。
    PENDING = "pending"
    #: 我加入。只有这一档算数。
    ACCEPTED = "accepted"
    #: 我不参加。**零负担**——不产生任何关系边，不留下任何记录给别人看。
    DECLINED = "declined"
    #: 我可以，但……。**不算同意**，会生成新一版条款。
    CONDITIONAL = "conditional"


#: 只有这一档算数。写成常量而不是散在各处的 `== ACCEPTED`——
#: 将来若要加档位（比如"暂时保留"），改这里一处就够，不用去找所有判断点。
COUNTS_AS_CONSENT: frozenset[CommitmentState] = frozenset({CommitmentState.ACCEPTED})


@dataclass(frozen=True, slots=True)
class Commitment:
    id: UUID
    proposal_id: UUID
    principal_id: UUID
    state: CommitmentState
    created_at: datetime
    expires_at: datetime
    #: 有条件接受时那句话的原文。**系统不解析它**——它是给人看的，
    #: 让系统去理解"但我周四要上课"再自动改条款，就是替人做了承诺。
    condition: str | None = None
    decided_at: datetime | None = None

    def is_decided(self) -> bool:
        return self.state is not CommitmentState.PENDING


class GateVerdict(StrEnum):
    """门开了没有，没开是因为什么。

    四种「没开」必须分得清：还在等人、有人拒绝、有人提了条件、过期了。
    合成一句"未通过"，界面上就只能显示一个转圈或者一句道歉。
    """

    #: 全员同意，可以成局。
    OPEN = "open"
    #: 还在等某些人。
    WAITING = "waiting"
    #: 有人明确拒绝。这一版条款作废。
    DECLINED = "declined"
    #: 有人提了条件。要出新一版，受影响的人重新确认。
    NEEDS_REVISION = "needs_revision"
    #: 决定窗口过了。没回的人不算拒绝，只是这次没赶上。
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class GateState:
    verdict: GateVerdict
    #: 还没回的人。「还在等谁」那一屏直接用它。
    waiting_on: tuple[UUID, ...] = ()
    #: 拒绝的人。**只给系统用来结束流程，不展示给其他成员**——
    #: 零负担拒绝的意思是拒绝的人不必向任何人解释。
    declined_by: tuple[UUID, ...] = ()
    #: 提了条件的人，连同他们的原话。
    conditions: tuple[tuple[UUID, str], ...] = ()

    @property
    def can_form(self) -> bool:
        return self.verdict is GateVerdict.OPEN


def terms_digest(
    *,
    member_ids: tuple[UUID, ...],
    role_assignment: dict[str, UUID],
    common_slots: tuple[int, ...],
    zone: str | None,
    deadline: datetime,
) -> str:
    """这一版条款的摘要。

    **哪些字段进摘要 = 哪些字段的变更会让旧同意失效**，所以这个清单
    就是"什么算实质变更"的定义，不是一个实现细节。

    进：人选、谁补哪个缺口、约定的时段、校区、截止时刻。
    不进：软目标得分、证明文案、提案的展示顺序——它们变了不影响
    "我答应的是这件事"这个判断。

    成员按 UUID 排序而不是按给出的顺序：同一批人换个顺序不是新条款。
    """
    payload = {
        "members": sorted(str(m) for m in member_ids),
        "roles": {k: str(v) for k, v in sorted(role_assignment.items())},
        "slots": sorted(common_slots),
        "zone": zone or "",
        "deadline": deadline.isoformat(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def evaluate(
    commitments: tuple[Commitment, ...],
    *,
    expected_members: tuple[UUID, ...],
    now: datetime,
) -> GateState:
    """门开了没有。

    **纯函数，不碰数据库。** 它决定的是"该不该成局"，成局本身是另一件事——
    分开之后，"什么条件下算通过"可以被单独测，而且改判据不用碰事务代码。

    没有承诺记录的成员按**还没回**算，不按拒绝算。这两者在产品上是两件事：
    没回的人可能只是没看到，拒绝的人是做了决定。
    """
    by_person = {c.principal_id: c for c in commitments}

    declined = tuple(
        pid
        for pid in expected_members
        if (c := by_person.get(pid)) is not None
        and c.state is CommitmentState.DECLINED
    )
    if declined:
        return GateState(verdict=GateVerdict.DECLINED, declined_by=declined)

    conditions = tuple(
        (pid, by_person[pid].condition or "")
        for pid in expected_members
        if (c := by_person.get(pid)) is not None
        and c.state is CommitmentState.CONDITIONAL
    )
    if conditions:
        return GateState(verdict=GateVerdict.NEEDS_REVISION, conditions=conditions)

    waiting = tuple(
        pid
        for pid in expected_members
        if (c := by_person.get(pid)) is None or c.state not in COUNTS_AS_CONSENT
    )
    if not waiting:
        return GateState(verdict=GateVerdict.OPEN)

    # 过期判断放在最后：已经有人拒绝或提了条件时，"过期"不是最有用的说法。
    deadline = min((c.expires_at for c in commitments), default=None)
    if deadline is not None and now >= deadline:
        return GateState(verdict=GateVerdict.EXPIRED, waiting_on=waiting)

    return GateState(verdict=GateVerdict.WAITING, waiting_on=waiting)
