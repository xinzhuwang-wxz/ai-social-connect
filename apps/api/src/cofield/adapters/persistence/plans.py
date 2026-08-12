"""行动确认卡的仓储。

PRD 把这张卡称作**最重要的中间转化节点**：从一句模糊的"有空一起"，
变成一项明确的共同承诺。

## 改了计划就得重新点头

`digest` 是这一版内容的摘要，**点头记在摘要上**。任何一项改动都换一个摘要，
于是"我点头的时候集合在北门，后来被改成南门"这件事不可能发生。

不用"改动之后清空点头"而用摘要，是因为前者依赖每一处写路径都记得清，
而后者由数据本身保证——少写一处清空，用户就会在一个自己没同意过的计划上
显示成已同意，而那是这个产品最不能出的错。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .schema import action_plans, plan_nods


@dataclass(frozen=True, slots=True)
class Plan:
    """一次行动的全部要素。

    任务和负责人**不在这里**——它们已经在 `space_items` 里了。复制一份的
    代价是两处会不一致，而不一致的那一刻，用户看到的是两个都像真的的计划。
    """

    id: UUID
    space_id: UUID
    title: str
    starts_at: datetime | None = None
    place: str | None = None
    bring: str | None = None
    budget: str | None = None
    change_note: str | None = None

    @property
    def digest(self) -> str:
        """这一版内容的摘要。

        只算**内容**，不算 id 和时间戳：同样的内容重新保存一次不该让
        所有人重新点一遍头。
        """
        # 用分隔符连：不加的话 "北门"+"手电" 和 "北"+"门手电" 会算出同一个摘要，
        # 而那意味着两份不同的计划共用一批点头。
        raw = "\u241f".join(
            [
                self.title.strip(),
                self.starts_at.isoformat() if self.starts_at else "",
                (self.place or "").strip(),
                (self.bring or "").strip(),
                (self.budget or "").strip(),
                (self.change_note or "").strip(),
            ]
        )
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    @property
    def settled(self) -> bool:
        """够不够格进入「待行动」。

        时间和地点是底线：一张没写什么时候、在哪的卡不是计划，是一个愿望。
        带什么和预算可以空——不是每件事都要带东西。
        """
        return bool(self.title.strip()) and self.starts_at is not None and bool(
            (self.place or "").strip()
        )


@dataclass(frozen=True, slots=True)
class PlanState:
    """这张卡现在是什么处境。"""

    plan: Plan
    #: 已经点头、而且点的是**现行这一版**的人。
    nodded: frozenset[UUID]
    #: 还没点头的人。界面上要指名道姓——"还差 2 个人"催不动任何人。
    waiting_on: tuple[UUID, ...]

    @property
    def confirmed(self) -> bool:
        """全员点头且要素齐了才算数。"""
        return not self.waiting_on and self.plan.settled


class PlanRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def get(self, space_id: UUID) -> Plan | None:
        row = self._conn.execute(
            sa.select(action_plans).where(action_plans.c.space_id == space_id)
        ).one_or_none()
        if row is None:
            return None
        return Plan(
            id=row.id,
            space_id=row.space_id,
            title=row.title,
            starts_at=row.starts_at,
            place=row.place,
            bring=row.bring,
            budget=row.budget,
            change_note=row.change_note,
        )

    def save(self, plan: Plan, *, by: UUID, now: datetime) -> Plan:
        """写入或改写。一个空间只有一张现行的卡。"""
        values = {
            "campus_id": self._campus,
            "space_id": plan.space_id,
            "title": plan.title.strip(),
            "starts_at": plan.starts_at,
            "place": plan.place,
            "bring": plan.bring,
            "budget": plan.budget,
            "change_note": plan.change_note,
            "digest": plan.digest,
            "updated_at": now,
        }
        row = self._conn.execute(
            pg_insert(action_plans)
            .values(id=plan.id, created_by=by, created_at=now, **values)
            .on_conflict_do_update(constraint="uq_plan_per_space", set_=values)
            .returning(action_plans.c.id)
        ).one()
        return replace(plan, id=row.id)

    def nod(self, plan: Plan, *, by: UUID, now: datetime) -> None:
        """点头。记在**这一版**的摘要上。"""
        self._conn.execute(
            pg_insert(plan_nods)
            .values(
                plan_id=plan.id,
                principal_id=by,
                campus_id=self._campus,
                digest=plan.digest,
                nodded_at=now,
            )
            .on_conflict_do_update(
                index_elements=[plan_nods.c.plan_id, plan_nods.c.principal_id],
                set_={"digest": plan.digest, "nodded_at": now},
            )
        )

    def state(self, plan: Plan, *, members: tuple[UUID, ...]) -> PlanState:
        rows = self._conn.execute(
            sa.select(plan_nods.c.principal_id)
            .where(plan_nods.c.plan_id == plan.id)
            # **对不上现行摘要的点头不算数。** 计划一改，所有人的点头一起失效。
            .where(plan_nods.c.digest == plan.digest)
        ).all()
        nodded = frozenset(r.principal_id for r in rows)
        return PlanState(
            plan=plan,
            nodded=nodded,
            waiting_on=tuple(m for m in members if m not in nodded),
        )

    def new(self, space_id: UUID, title: str) -> Plan:
        return Plan(id=uuid4(), space_id=space_id, title=title)
