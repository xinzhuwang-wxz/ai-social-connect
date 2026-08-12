"""到那天了：我准备好了、我出发了、我到了；以及做完了没有。

PRD 的「线下转化」这一段。产品能把人凑齐、能定下计划，然后到此为止——
而 PRD 说得很清楚：这个产品不以"双方聊起来"为终点，以**真的一起完成了
一次行动**为终点。

## 状态不是条目

条目是"要做的事"：有负责人、有截止、进不进度。而"我出发了"是一个人**此刻
的处境**——每人一条、会来回改、行动结束就没意义了。混进条目里，进度条会
被一堆"我到了"顶满，而不变量 6 说的正是共域因真实行动证据生长。

## 完成要全员点头

一个人说"做完了"就把事情标记成完成，等于让他替所有人宣布。
而这件事会写进每个人的森林。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .schema import day_of_states, done_marks


class DayOf(StrEnum):
    """到那天了，我现在什么处境。

    四档就够。**没有"我迟到 10 分钟"**——那是一句话，说在群里比点一个
    状态清楚，而多一档状态就多一次"该点哪个"的犹豫。
    """

    #: 东西备齐了。
    READY = "ready"
    #: 我出发了。
    LEAVING = "leaving"
    #: 我到了。
    ARRIVED = "arrived"
    #: 临时有变。**必须能带一句话**，不然它只是一个让人干着急的标记。
    CHANGED = "changed"


WORDS: dict[DayOf, str] = {
    DayOf.READY: "准备好了",
    DayOf.LEAVING: "出发了",
    DayOf.ARRIVED: "到了",
    DayOf.CHANGED: "临时有变",
}


@dataclass(frozen=True, slots=True)
class Standing:
    principal_id: UUID
    state: DayOf
    note: str | None
    updated_at: datetime

    @property
    def word(self) -> str:
        return WORDS[self.state]


class GoingRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    # --- 到那天了 ---

    def set_state(
        self,
        space_id: UUID,
        *,
        by: UUID,
        state: DayOf,
        note: str | None,
        now: datetime,
    ) -> None:
        """改自己的状态。**每人一条，覆盖**——它是处境不是历史。"""
        values = {"state": state.value, "note": note, "updated_at": now}
        self._conn.execute(
            pg_insert(day_of_states)
            .values(
                space_id=space_id, principal_id=by, campus_id=self._campus, **values
            )
            .on_conflict_do_update(
                index_elements=[day_of_states.c.space_id, day_of_states.c.principal_id],
                set_=values,
            )
        )

    def standings(self, space_id: UUID) -> tuple[Standing, ...]:
        rows = self._conn.execute(
            sa.select(day_of_states).where(day_of_states.c.space_id == space_id)
        ).all()
        return tuple(
            Standing(
                principal_id=r.principal_id,
                state=DayOf(r.state),
                note=r.note,
                updated_at=r.updated_at,
            )
            for r in rows
        )

    # --- 做完了 ---

    def mark_done(self, space_id: UUID, *, by: UUID, now: datetime) -> None:
        self._conn.execute(
            pg_insert(done_marks)
            .values(
                space_id=space_id,
                principal_id=by,
                campus_id=self._campus,
                marked_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[done_marks.c.space_id, done_marks.c.principal_id]
            )
        )

    def unmark_done(self, space_id: UUID, *, by: UUID) -> None:
        """点错了要能收回。

        不给收回的路，人就不敢点——而"不敢点"会让这一步整个失效。
        """
        self._conn.execute(
            sa.delete(done_marks)
            .where(done_marks.c.space_id == space_id)
            .where(done_marks.c.principal_id == by)
        )

    def who_marked(self, space_id: UUID) -> frozenset[UUID]:
        rows = self._conn.execute(
            sa.select(done_marks.c.principal_id).where(
                done_marks.c.space_id == space_id
            )
        ).all()
        return frozenset(r.principal_id for r in rows)
