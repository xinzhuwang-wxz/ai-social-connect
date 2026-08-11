"""承诺仓储。

**只接受真人签名的命令。** 这张表没有任何自动写入的路径——
不是"约定上不这么做"，是这一层根本没提供那样的方法。

改主意是改同一行（`(proposal_id, principal_id)` 上有唯一约束），
不是追加一行——否则"他到底答应了没有"会有两个答案。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection, Row
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.formation.gate import Commitment, CommitmentState

from .schema import commitments


def _to_domain(row: Row[tuple[object, ...]]) -> Commitment:
    return Commitment(
        id=row.id,
        proposal_id=row.proposal_id,
        principal_id=row.principal_id,
        state=CommitmentState(row.state),
        condition=row.condition,
        decided_at=row.decided_at,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


class CommitmentRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def open_for(
        self,
        proposal_id: UUID,
        member_ids: tuple[UUID, ...],
        *,
        now: datetime,
        expires_at: datetime,
    ) -> int:
        """给这一版条款的每个成员开一条待答复。

        重复调用不重开：已经有答复的人不该因为运维重跑一次清算
        就被清回「还没回」。
        """
        if not member_ids:
            return 0
        rows = [
            {
                "id": uuid4(),
                "campus_id": self._campus,
                "proposal_id": proposal_id,
                "principal_id": member_id,
                "state": CommitmentState.PENDING.value,
                "created_at": now,
                "expires_at": expires_at,
            }
            for member_id in member_ids
        ]
        stmt = pg_insert(commitments).values(rows)
        # 数 RETURNING 回来的行，不看 rowcount——`ON CONFLICT DO NOTHING`
        # 下驱动给的 rowcount 是 -1，拿它当"新开了几条"会静默错。
        inserted = self._conn.execute(
            stmt.on_conflict_do_nothing(
                constraint="uq_commitment_person"
            ).returning(commitments.c.id)
        ).all()
        return len(inserted)

    def decide(
        self,
        proposal_id: UUID,
        principal_id: UUID,
        *,
        state: CommitmentState,
        now: datetime,
        condition: str | None = None,
    ) -> Commitment | None:
        """一个真人做出决定。

        `PENDING` 不接受：把答复改回「还没回」是一个没有真实含义的动作，
        允许它只会制造一种绕过门槛的方式。想反悔就明确拒绝。

        返回 `None` 表示这个人不在这一版条款的名单里——
        **不静默创建**，否则任何人都能给任意提案投票。
        """
        if state is CommitmentState.PENDING:
            raise ValueError("不能把答复改回「还没回」——想反悔就明确拒绝")
        if state is CommitmentState.CONDITIONAL and not (condition or "").strip():
            raise ValueError("有条件接受必须说清条件是什么，否则对方无从回应")

        row = self._conn.execute(
            sa.update(commitments)
            .where(commitments.c.proposal_id == proposal_id)
            .where(commitments.c.principal_id == principal_id)
            .values(state=state.value, condition=condition, decided_at=now)
            .returning(commitments)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def for_proposal(self, proposal_id: UUID) -> tuple[Commitment, ...]:
        rows = self._conn.execute(
            sa.select(commitments).where(commitments.c.proposal_id == proposal_id)
        ).all()
        return tuple(_to_domain(r) for r in rows)
