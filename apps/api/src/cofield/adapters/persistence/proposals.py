"""成局提案仓储。

提案**不是**共同事件。它只是"我们觉得这几个人能凑一队"——事件要等全员
真人确认才诞生。所以这张表里没有任何表示"已成局"的状态，也没有任何方法
能把提案直接变成事件。

成局证明以 JSON 存原结构而不是拆成列：它是**机器可读的证据**，
申诉、A/B 与审计都读它，拆开存迟早会丢掉某一条。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from cofield.matching.contracts import FormationProof

from .schema import formation_proposals


@dataclass(frozen=True, slots=True)
class Proposal:
    """一次清算给一条需求产出的一个小队。

    它住在持久化这一侧而不是撮合那一侧，是为了让依赖单向：
    撮合写库，库不反过来知道撮合是怎么算出来的。
    """

    id: UUID
    intent_id: UUID
    action_kind: str | None
    cleared_at: datetime
    member_ids: tuple[UUID, ...]
    proof: FormationProof
    expires_at: datetime



def _jsonable(value: Any) -> Any:
    """把证明结构变成可存的 JSON。

    枚举取值、时间取 ISO 串、其余递归。不用 pydantic：这一层不该为了
    序列化把领域结构拖进某个框架的类型体系。
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


class ProposalRepository:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def add(self, proposal: Proposal) -> None:
        self._conn.execute(
            sa.insert(formation_proposals).values(
                id=proposal.id,
                campus_id=self._campus,
                intent_id=proposal.intent_id,
                action_kind=proposal.action_kind,
                cleared_at=proposal.cleared_at,
                member_ids=list(proposal.member_ids),
                proof=_jsonable(proposal.proof),
                # 恒为真——不稳定的分区在写库之前就被拦掉了。
                # 存下来是为了让"这条不变量有没有被绕过"可被查询验证。
                stability_passed=_passed(proposal.proof),
                expires_at=proposal.expires_at,
            )
        )

    def exists_since(self, intent_id: UUID, *, since: datetime) -> bool:
        """这条需求在这个清算边界上是否已经出过提案。

        清算重复调用是安全的，靠的就是这个判断——`cleared_at` 记的是
        **边界时刻**而不是"跑这一次的时刻"，所以同一个窗口内幂等。
        """
        return (
            self._conn.execute(
                sa.select(sa.literal(1))
                .select_from(formation_proposals)
                .where(formation_proposals.c.intent_id == intent_id)
                .where(formation_proposals.c.cleared_at >= since)
                .limit(1)
            ).first()
            is not None
        )

    def outstanding_for(self, intent_id: UUID, *, now: datetime) -> bool:
        """这条需求还有没有人正等着答复。

        和 `exists_since` 不是一回事：那个问的是"这个窗口跑过没有"，
        用于清算幂等；这个问的是"外面还有没有一份没答的邀请"，用于挡住
        **人主动按第二次**——那一路没有清算边界可依，边界只能是"上一份
        还活着"。

        过期的不算：有效期过了，被邀的人多半已经答应了别的事，这时候
        再问一次是重新开始，不是重复轰炸。
        """
        return (
            self._conn.execute(
                sa.select(sa.literal(1))
                .select_from(formation_proposals)
                .where(formation_proposals.c.intent_id == intent_id)
                .where(formation_proposals.c.expires_at > now)
                .limit(1)
            ).first()
            is not None
        )

    def list_for_intent(self, intent_id: UUID, *, now: datetime) -> list[Row[Any]]:
        """给「给你找的人」那一屏。过期的不给——过了有效期，
        被提案的人很可能已经答应了别的事，再展示等于让用户白跑一趟。"""
        return list(
            self._conn.execute(
                sa.select(formation_proposals)
                .where(formation_proposals.c.intent_id == intent_id)
                .where(formation_proposals.c.expires_at > now)
                .order_by(formation_proposals.c.cleared_at.desc())
            ).all()
        )


def _passed(proof: FormationProof) -> bool:
    return proof.stability is not None and proof.stability.passed
