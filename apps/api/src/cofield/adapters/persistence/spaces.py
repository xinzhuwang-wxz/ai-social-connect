"""共域仓储：读空间，写条目。

**这里没有「创建空间」。** 共域在确认门里随共同事件一起、在同一个事务内诞生
（不变量 3：成局前只有提案，没有关系）。留一个从外面凭空建空间的入口，
就等于留了一条绕过确认门的路——所以这不是遗漏，是这一层的边界。

条目全部落在一张表上，靠 `kind` 区分。新增一种条目是新增一条声明，
不是新增一张表加一套 CRUD——这和行动类别注册表是同一个扩展点思路。
规则住在 `cofield.space.canvas`，这里只负责行与对象之间的搬运。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from .schema import space_items, spaces


@dataclass(frozen=True, slots=True)
class Space:
    """一个事件的空间。一个事件一个，不是可以开好几个的群。

    `agent_enabled` 是助手开关。它是一列布尔值而不是一套权限体系，
    因为助手在这个产品里就只是画布上的一张卡片——关掉它，
    共域必须照常可用。
    """

    id: UUID
    event_id: UUID
    name: str
    agent_enabled: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Item:
    """画布上的一条东西。

    每条都有类型、状态、负责人和截止时刻——群聊里没有这四样，
    所以群聊里的信息会沉底、决定没有归属。

    `drafted_by_agent` 与 `accepted_by` 是一对：前者记谁写的，
    后者记谁认了。分不清谁写的，"人类决定"就只是一句话。
    """

    id: UUID
    space_id: UUID
    kind: str
    title: str
    state: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    body: str | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    drafted_by_agent: bool = False
    accepted_by: UUID | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def awaiting_a_person(self) -> bool:
        """助手写的，还没有真人认领这个决定。"""
        return self.drafted_by_agent and self.accepted_by is None


def _to_item(row: Row[Any]) -> Item:
    return Item(
        id=row.id,
        space_id=row.space_id,
        kind=row.kind,
        title=row.title,
        state=row.state,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        body=row.body,
        assignee_id=row.assignee_id,
        due_at=row.due_at,
        drafted_by_agent=row.drafted_by_agent,
        accepted_by=row.accepted_by,
        extras=dict(row.extras or {}),
    )


class SpaceRepository:
    """租户由连接绑定（见 `engine.campus_connection`），这里不写 WHERE campus。

    `campus_id` 仍然要传：写入时那一列必须填对，填错会被策略的 WITH CHECK
    直接拒掉——这正是我们要的，越租户写入应该是数据库层的错误，
    不是应用层记得加过滤的结果。
    """

    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    # --- 读空间 ---

    def get(self, space_id: UUID) -> Space | None:
        row = self._conn.execute(
            sa.select(spaces).where(spaces.c.id == space_id)
        ).one_or_none()
        return _to_space(row) if row is not None else None

    def for_event(self, event_id: UUID) -> Space | None:
        """事件的空间。`event_id` 上有唯一约束，所以最多一条。"""
        row = self._conn.execute(
            sa.select(spaces).where(spaces.c.event_id == event_id)
        ).one_or_none()
        return _to_space(row) if row is not None else None

    def set_agent_enabled(self, space_id: UUID, *, enabled: bool) -> None:
        """开关助手。

        这不是创建空间，是空间存在之后成员自己的一个选择。它必须顺手——
        一个需要走流程才能关掉的助手，等于关不掉。
        """
        self._conn.execute(
            sa.update(spaces)
            .where(spaces.c.id == space_id)
            .values(agent_enabled=enabled)
        )

    # --- 写条目 ---

    def add_item(self, item: Item) -> None:
        self._conn.execute(sa.insert(space_items).values(**self._row(item)))

    def save_item(self, item: Item) -> None:
        """整条覆盖。条目是小对象，字段级更新只会让调用方多记一件事。"""
        values = self._row(item)
        for immutable in ("id", "campus_id", "space_id", "created_by", "created_at"):
            values.pop(immutable)
        self._conn.execute(
            sa.update(space_items).where(space_items.c.id == item.id).values(**values)
        )

    def get_item(self, item_id: UUID) -> Item | None:
        row = self._conn.execute(
            sa.select(space_items).where(space_items.c.id == item_id)
        ).one_or_none()
        return _to_item(row) if row is not None else None

    def list_items(
        self, space_id: UUID, *, kinds: Sequence[str] | None = None
    ) -> list[Item]:
        """按写下的先后返回。

        画布不按状态或优先级排序——那会让同一块屏幕在两个人眼里长得不一样，
        而"我们看见的是同一件事"正是这个空间存在的理由。
        """
        stmt = sa.select(space_items).where(space_items.c.space_id == space_id)
        if kinds is not None:
            stmt = stmt.where(space_items.c.kind.in_(list(kinds)))
        rows = self._conn.execute(stmt.order_by(space_items.c.created_at.asc())).all()
        return [_to_item(r) for r in rows]

    def _row(self, item: Item) -> dict[str, Any]:
        return {
            "id": item.id,
            "campus_id": self._campus,
            "space_id": item.space_id,
            "kind": item.kind,
            "title": item.title,
            "body": item.body,
            "state": item.state,
            "assignee_id": item.assignee_id,
            "due_at": item.due_at,
            "drafted_by_agent": item.drafted_by_agent,
            "accepted_by": item.accepted_by,
            "created_by": item.created_by,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "extras": dict(item.extras),
        }


def _to_space(row: Row[Any]) -> Space:
    return Space(
        id=row.id,
        event_id=row.event_id,
        name=row.name,
        agent_enabled=row.agent_enabled,
        created_at=row.created_at,
    )
