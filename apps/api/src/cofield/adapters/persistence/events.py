"""共同事件的诞生。**要么全有，要么全无。**

这是整个产品里唯一创造关系边的地方。事件、成员关系、共域三者在
**同一个事务**里出现——达不到门槛时一个都不出现，不是"先建个草稿再说"。

半成品最伤人：如果先建一个草稿事件再慢慢凑人，参与者会以为已经成了，
他会去排时间、去准备、去跟别人说。等到发现没凑齐，损失的不是一次匹配，
是一次信任。宁可什么都没有，不要一个像成了的东西。

## 场域智能体的授权不在这个事务里

它在**提交之后**才生成。理由是这两件事的失败后果不对称：事务回滚掉一个
本该存在的事件，用户会以为系统坏了；而多发一张 agent 令牌给一个不存在的
空间，是一个真实的权限泄漏。把授权放在事务里，等于让权限的正确性依赖
事务的成败。

## 幂等

同一个提案重复确认不产生第二个事件——靠 `uq_event_per_proposal` 这条
唯一约束，不靠"先查一下再插"。并发下先查后插会同时通过检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .schema import event_members, shared_events, space_items, spaces


@dataclass(frozen=True, slots=True)
class FormedEvent:
    """刚刚诞生的一件事，连同它的空间。"""

    event_id: UUID
    space_id: UUID
    member_ids: tuple[UUID, ...]
    formed_at: datetime
    #: 这次调用是不是真的创建了它。重复确认时为 `False`——
    #: 调用方据此决定要不要发通知，避免第二次确认又给所有人发一遍。
    created: bool


class EventRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def form(
        self,
        *,
        proposal_id: UUID,
        action_kind: str | None,
        title: str,
        goal: str,
        steward_id: UUID,
        member_ids: tuple[UUID, ...],
        role_assignment: dict[str, UUID],
        deadline: datetime | None,
        first_action: str | None,
        now: datetime,
    ) -> FormedEvent:
        """在一个事务里创建事件、成员关系与共域。

        调用方**必须**先通过确认门。这一层不重复判断门槛——两处判断迟早
        会不一致，而且会让"门槛是什么"变成两个地方的共识而不是一处的定义。

        `steward_id` 不能为空：没有真人负责人的自动成局会导致责任分散。
        """
        if not member_ids:
            raise ValueError("没有成员的事件不该存在")
        if steward_id not in member_ids:
            raise ValueError("负责人必须是成员之一——挂名负责等于没有负责人")

        event_id = uuid4()
        inserted = self._conn.execute(
            pg_insert(shared_events)
            .values(
                id=event_id,
                campus_id=self._campus,
                proposal_id=proposal_id,
                action_kind=action_kind,
                title=title,
                goal=goal,
                steward_id=steward_id,
                formed_at=now,
                deadline=deadline,
                state="active",
            )
            # 幂等靠唯一约束，不靠"先查一下再插"——并发下先查后插会同时通过。
            .on_conflict_do_nothing(constraint="uq_event_per_proposal")
            .returning(shared_events.c.id)
        ).one_or_none()

        if inserted is None:
            existing = self._conn.execute(
                sa.select(shared_events.c.id, shared_events.c.formed_at).where(
                    shared_events.c.proposal_id == proposal_id
                )
            ).one()
            space_id = self._conn.execute(
                sa.select(spaces.c.id).where(spaces.c.event_id == existing.id)
            ).scalar_one()
            return FormedEvent(
                event_id=existing.id,
                space_id=space_id,
                member_ids=member_ids,
                formed_at=existing.formed_at,
                created=False,
            )

        role_of = {person: role for role, person in role_assignment.items()}
        self._conn.execute(
            sa.insert(event_members),
            [
                {
                    "event_id": event_id,
                    "principal_id": member_id,
                    "campus_id": self._campus,
                    "role": role_of.get(member_id),
                    "joined_at": now,
                }
                for member_id in member_ids
            ],
        )

        space_id = uuid4()
        self._conn.execute(
            sa.insert(spaces).values(
                id=space_id,
                campus_id=self._campus,
                event_id=event_id,
                name=title,
                agent_enabled=True,
                created_at=now,
            )
        )

        # 成员共同定下的第一个动作要成为空间里看得见的东西。
        # 空空的共域和群聊没区别——第一屏就该有一件具体的事可做，
        # 而它必须来自大家刚刚确认的内容，不是系统编的欢迎语。
        if first_action:
            self._conn.execute(
                sa.insert(space_items).values(
                    id=uuid4(),
                    campus_id=self._campus,
                    space_id=space_id,
                    kind="task",
                    title=first_action,
                    # **必须是 `task` 自己声明过的状态。**
                    # 这里原来写的是 `open`（决策门的初始态），于是每个新空间的
                    # 第一张卡都处在自己类型没有的状态里——推进和进度都建在
                    # 那张声明表上，一个不在表里的值让两者同时失去意义，
                    # 而界面上它看起来完全正常。
                    state="todo",
                    assignee_id=steward_id,
                    due_at=deadline,
                    drafted_by_agent=False,
                    created_by=steward_id,
                    created_at=now,
                    updated_at=now,
                    extras={},
                )
            )

        return FormedEvent(
            event_id=event_id,
            space_id=space_id,
            member_ids=member_ids,
            formed_at=now,
            created=True,
        )

    def for_proposal(self, proposal_id: UUID) -> UUID | None:
        return self._conn.execute(
            sa.select(shared_events.c.id).where(
                shared_events.c.proposal_id == proposal_id
            )
        ).scalar_one_or_none()

    def count_edges(self, principal_id: UUID) -> int:
        """这个人身上有几条关系边。

        「未获真人确认的提案不创建关系边」这条不变量靠它验证——
        测试断言的是一个可查询的数字，不是"我们没写那行代码"。
        """
        return self._conn.execute(
            sa.select(sa.func.count())
            .select_from(event_members)
            .where(event_members.c.principal_id == principal_id)
        ).scalar_one()
