"""确认门的执行侧：把一次真人确认变成一次状态推进。

领域判断在 `gate.py`（纯函数），事务在 `adapters/persistence/events.py`。
这一层只负责把两者接起来，并且守住一件事：**没通过门就不许碰事务。**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection

from cofield.adapters.persistence.commitments import CommitmentRepository
from cofield.adapters.persistence.events import EventRepository, FormedEvent
from cofield.adapters.persistence.schema import formation_proposals
from cofield.formation.gate import (
    DECISION_WINDOW,
    CommitmentState,
    GateState,
    GateVerdict,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class Outcome:
    """一次确认之后发生了什么。"""

    state: GateState
    #: 成局了才有。
    formed: FormedEvent | None = None
    #: 有人提条件时生成的新一版提案。旧的那版同时作废。
    revised_proposal_id: UUID | None = None
    #: 需要在**事务提交之后**做的事。现在只有一件：给场域智能体发授权。
    #: 放在这里而不是直接做掉，是因为这两件事的失败后果不对称——
    #: 事务回滚掉一个本该存在的事件，用户会以为系统坏了；
    #: 而多发一张令牌给一个不存在的空间，是一个真实的权限泄漏。
    grant_agent_for_space: UUID | None = None


class ConfirmationGate:
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id
        self._commitments = CommitmentRepository(conn, campus_id)
        self._events = EventRepository(conn, campus_id)

    def invite(self, proposal_id: UUID, *, now: datetime) -> int:
        """给这一版条款的每个成员开一条待答复。"""
        row = self._proposal(proposal_id)
        expires_at = min(row.expires_at, now + DECISION_WINDOW)
        return self._commitments.open_for(
            proposal_id,
            tuple(row.member_ids),
            now=now,
            expires_at=expires_at,
        )

    def decide(
        self,
        proposal_id: UUID,
        principal_id: UUID,
        *,
        state: CommitmentState,
        now: datetime,
        condition: str | None = None,
    ) -> Outcome:
        """一个真人做出决定，然后看门开了没有。

        **只有这一个入口能推动成局。** 没有任何自动路径、没有超时自动同意、
        没有"负责人代其他人确认"——AI 可以代为表达，但不能代为承诺。
        """
        row = self._proposal(proposal_id)
        if row.withdrawn_at is not None:
            raise ValueError("这一版条款已经作废了，去看新的那版")

        written = self._commitments.decide(
            proposal_id,
            principal_id,
            state=state,
            now=now,
            condition=condition,
        )
        if written is None:
            # 不静默创建：否则任何人都能给任意提案投票。
            raise ValueError("这个人不在这一版条款的名单里")

        verdict = evaluate(
            self._commitments.for_proposal(proposal_id),
            expected_members=tuple(row.member_ids),
            now=now,
        )

        if verdict.verdict is GateVerdict.NEEDS_REVISION:
            return Outcome(
                state=verdict,
                revised_proposal_id=self._revise(row, now=now),
            )

        if verdict.verdict is GateVerdict.DECLINED:
            # 体面结束：作废这一版，不留任何关系边，也不给拒绝的人留记录。
            self._withdraw(proposal_id, now=now)
            return Outcome(state=verdict)

        if not verdict.can_form:
            return Outcome(state=verdict)

        formed = self._events.form(
            proposal_id=proposal_id,
            action_kind=row.action_kind,
            title=_title_of(row),
            goal=_goal_of(row),
            steward_id=row.member_ids[0],
            member_ids=tuple(row.member_ids),
            role_assignment={},
            deadline=row.expires_at,
            first_action=_first_action_of(row),
            now=now,
        )
        return Outcome(
            state=verdict,
            formed=formed,
            grant_agent_for_space=formed.space_id if formed.created else None,
        )

    def status(self, proposal_id: UUID, *, now: datetime) -> GateState:
        """还在等谁。这一屏只展示未决事项，已决的折叠起来。"""
        row = self._proposal(proposal_id)
        return evaluate(
            self._commitments.for_proposal(proposal_id),
            expected_members=tuple(row.member_ids),
            now=now,
        )

    # --- 内部 ---

    def _proposal(self, proposal_id: UUID) -> sa.Row[tuple[object, ...]]:
        row = self._conn.execute(
            sa.select(formation_proposals).where(
                formation_proposals.c.id == proposal_id
            )
        ).one_or_none()
        if row is None:
            raise ValueError("找不到这个提案")
        return row

    def _withdraw(self, proposal_id: UUID, *, now: datetime) -> None:
        self._conn.execute(
            sa.update(formation_proposals)
            .where(formation_proposals.c.id == proposal_id)
            .values(withdrawn_at=now)
        )

    def _revise(self, row: sa.Row[tuple[object, ...]], *, now: datetime) -> UUID:
        """条件接受生成新一版。

        **新增一行，不改旧行。** 谁在哪一版上答应过什么，申诉时要查得出来。
        新版的条款摘要必然不同（版本号进了摘要），所以旧的那些「我加入」
        自动不再指向现在这件事——不需要有人记得去清空承诺表。
        """
        new_id = uuid4()
        proof = dict(row.proof) if isinstance(row.proof, dict) else row.proof
        self._conn.execute(
            sa.insert(formation_proposals).values(
                id=new_id,
                campus_id=self._campus,
                intent_id=row.intent_id,
                action_kind=row.action_kind,
                cleared_at=row.cleared_at,
                member_ids=list(row.member_ids),
                proof=proof,
                stability_passed=row.stability_passed,
                expires_at=row.expires_at,
                terms_digest=f"{row.terms_digest}:v{row.version + 1}",
                version=row.version + 1,
                supersedes=row.id,
            )
        )
        self._withdraw(row.id, now=now)
        return new_id


def _title_of(row: sa.Row[tuple[object, ...]]) -> str:
    proof = row.proof if isinstance(row.proof, dict) else {}
    satisfied = proof.get("satisfied") or []
    if satisfied and isinstance(satisfied[0], dict):
        return str(satisfied[0].get("text", ""))[:60] or "我们的项目"
    return "我们的项目"


def _goal_of(row: sa.Row[tuple[object, ...]]) -> str:
    proof = row.proof if isinstance(row.proof, dict) else {}
    lines = proof.get("satisfied") or []
    if lines and isinstance(lines[0], dict):
        return str(lines[0].get("text", ""))
    return ""


def _first_action_of(row: sa.Row[tuple[object, ...]]) -> str | None:
    """大家共同定下的第一个动作。

    取的是证明里「必须由真人决定的事」的第一条——那正是这群人接下来
    真的要碰面解决的问题。空空的共域和群聊没区别；第一屏就该有一件
    具体的事，而它必须来自刚刚确认的内容，不是系统编的欢迎语。
    """
    proof = row.proof if isinstance(row.proof, dict) else {}
    for_humans = proof.get("for_humans") or []
    if for_humans and isinstance(for_humans[0], dict):
        text = str(for_humans[0].get("text", "")).strip()
        return text or None
    return None
