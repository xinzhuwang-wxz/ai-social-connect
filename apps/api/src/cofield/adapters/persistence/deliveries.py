"""种子投到了谁那里，以及他怎么答的。

## 这一层承载的产品判断

**发起人面对的每一个人都已经说过愿意。** 旧链路让他挑一支队然后等对方
理不理你——"石沉大海"正是这个产品要消灭的第二个痛点。

所以流程是：投给多人 → 候选表态 → 发起人**在愿意的人里**挑，
挑到种子要的人数收满为止。

## 一对一，不是一支队

每个候选各自一条：各自的状态、各自的留言、各自的"为什么投给他"。
这就是它不能塞进 `formation_proposals` 的原因——那张表的 `member_ids`
说的是"一支队的成员"，而这里是一批互不相干的人。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .schema import seed_deliveries


class Delivered(StrEnum):
    """一颗种子在一个人那里的处境。"""

    #: 投到了，还没答。
    DELIVERED = "delivered"
    #: 我愿意参与。**这不是承诺加入**——还要发起人挑中才算成局。
    WILLING = "willing"
    #: 这次不感兴趣。零负担：不问为什么，不留任何记录给别人看。
    PASSED = "passed"
    #: 发起人挑中了他。
    CHOSEN = "chosen"
    #: 这颗种子已经找到同行者了。
    #:
    #: **给没被选中的人看的话是"已经找到同行者"，不是"你没被选上"**——
    #: 前者说的是这颗种子的处境，后者是对他的评价，而这里没有评价。
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Delivery:
    intent_id: UUID
    principal_id: UUID
    state: Delivered
    why: tuple[str, ...]
    rank: int
    note: str | None = None
    delivered_at: datetime | None = None


class DeliveryRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def deliver(
        self,
        intent_id: UUID,
        *,
        to: list[tuple[UUID, tuple[str, ...]]],
        now: datetime,
    ) -> int:
        """把种子投给这几个人，附上各自的理由。

        重复投递不覆盖已经答过的：一个说过"不感兴趣"的人不该在下一轮
        清算里被重新问一遍——**同一件事问第二遍最伤**。
        """
        if not to:
            return 0
        rows = [
            {
                "intent_id": intent_id,
                "principal_id": who,
                "campus_id": self._campus,
                "state": Delivered.DELIVERED.value,
                "why": list(why),
                "rank": index,
                "delivered_at": now,
            }
            for index, (who, why) in enumerate(to)
        ]
        self._conn.execute(
            pg_insert(seed_deliveries)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    seed_deliveries.c.intent_id,
                    seed_deliveries.c.principal_id,
                ]
            )
        )
        return len(rows)

    def answer(
        self,
        intent_id: UUID,
        *,
        by: UUID,
        willing: bool,
        note: str | None,
        now: datetime,
    ) -> Delivery | None:
        """候选表态。

        只能答**还没答过的**：改主意要靠重新沟通，不是靠反复切换按钮——
        发起人已经在据此挑人了。
        """
        row = self._conn.execute(
            sa.update(seed_deliveries)
            .where(seed_deliveries.c.intent_id == intent_id)
            .where(seed_deliveries.c.principal_id == by)
            .where(seed_deliveries.c.state == Delivered.DELIVERED.value)
            .values(
                state=(Delivered.WILLING if willing else Delivered.PASSED).value,
                note=(note or "").strip() or None,
                answered_at=now,
            )
            .returning(seed_deliveries)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def choose(self, intent_id: UUID, *, who: UUID, now: datetime) -> Delivery | None:
        """发起人挑中一个人。**只能从说过愿意的人里挑。**"""
        row = self._conn.execute(
            sa.update(seed_deliveries)
            .where(seed_deliveries.c.intent_id == intent_id)
            .where(seed_deliveries.c.principal_id == who)
            .where(seed_deliveries.c.state == Delivered.WILLING.value)
            .values(state=Delivered.CHOSEN.value, answered_at=now)
            .returning(seed_deliveries)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def close_rest(self, intent_id: UUID) -> int:
        """收满了，其余的都关掉。

        他们看到的是「这颗种子已经找到同行者」——**说的是种子的处境，
        不是对他们的评价**。
        """
        result = self._conn.execute(
            sa.update(seed_deliveries)
            .where(seed_deliveries.c.intent_id == intent_id)
            .where(
                seed_deliveries.c.state.in_(
                    [Delivered.DELIVERED.value, Delivered.WILLING.value]
                )
            )
            .values(state=Delivered.CLOSED.value)
        )
        return result.rowcount

    def inbox(self, principal_id: UUID) -> tuple[Delivery, ...]:
        """我收到的种子。已经关掉的不再占地方。"""
        rows = self._conn.execute(
            sa.select(seed_deliveries)
            .where(seed_deliveries.c.principal_id == principal_id)
            .where(seed_deliveries.c.state != Delivered.CLOSED.value)
            .order_by(seed_deliveries.c.delivered_at.desc())
        ).all()
        return tuple(_to_domain(r) for r in rows)

    def for_intent(self, intent_id: UUID) -> tuple[Delivery, ...]:
        rows = self._conn.execute(
            sa.select(seed_deliveries)
            .where(seed_deliveries.c.intent_id == intent_id)
            .order_by(seed_deliveries.c.rank.asc())
        ).all()
        return tuple(_to_domain(r) for r in rows)

    def chosen(self, intent_id: UUID) -> tuple[UUID, ...]:
        rows = self._conn.execute(
            sa.select(seed_deliveries.c.principal_id)
            .where(seed_deliveries.c.intent_id == intent_id)
            .where(seed_deliveries.c.state == Delivered.CHOSEN.value)
        ).all()
        return tuple(r.principal_id for r in rows)

    def delivered_since(self, intent_id: UUID, *, since: datetime) -> bool:
        """这个边界之后，这颗种子已经投过了没有。

        **清算幂等靠它。** 少了这一步，同一条需求每跑一次清算就再投给
        几个新人——而候选那一侧收到的是一封又一封"有人想找你"，
        像垃圾邮件。
        """
        return (
            self._conn.execute(
                sa.select(seed_deliveries.c.principal_id)
                .where(seed_deliveries.c.intent_id == intent_id)
                .where(seed_deliveries.c.delivered_at >= since)
                .limit(1)
            ).first()
            is not None
        )

    def already_touched(self, intent_id: UUID) -> frozenset[UUID]:
        """已经投过的人。下一轮清算不再投给他们。"""
        rows = self._conn.execute(
            sa.select(seed_deliveries.c.principal_id).where(
                seed_deliveries.c.intent_id == intent_id
            )
        ).all()
        return frozenset(r.principal_id for r in rows)


def _to_domain(row: sa.Row[tuple[object, ...]]) -> Delivery:
    return Delivery(
        intent_id=row.intent_id,
        principal_id=row.principal_id,
        state=Delivered(row.state),
        why=tuple(row.why or ()),
        rank=row.rank,
        note=row.note,
        delivered_at=row.delivered_at,
    )
