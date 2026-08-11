"""等配队、给你找的人、还差这几件事。

这三屏共享一条产品规则：**任何一屏都不能是空白页**。

- 还在等 → 说清什么时候配队、这个方向上现在缺什么
- 有小队了 → 每队附可逐条追溯的理由，没有百分比
- 凑不出来 → 说清卡在哪、放宽哪一项能多出多少人、下一步能做什么

第三种最容易被做成一句"暂无结果"，而那正是用户流失的地方。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.adapters.persistence.proposals import ProposalRepository
from cofield.adapters.persistence.schema import formation_proposals
from cofield.catalog import registry as action_kinds
from cofield.formation.gate import CommitmentState
from cofield.formation.service import ConfirmationGate
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep, ReposDep
from cofield.matching.blocking import explain_recall
from cofield.matching.funnel import Funnel
from cofield.matching.window import Clearing, MarketBoard

router = APIRouter(tags=["proposals"])


# --- 响应形状 ---


class GapOut(BaseModel):
    """一样本事：多少人要、多少人给得出。只给聚合数，不给名字。"""

    skill: str
    wanted: int
    offered: int
    scarce: bool


class WaitingOut(BaseModel):
    """「等配队」那一屏。

    光说"请稍候"用户只会走掉；说"现在 12 个人缺剪辑，只有 3 个人会"，
    他就知道该改需求、该去拉人、还是该自己顶上。
    """

    next_round_at: str
    waiting_count: int
    gaps: list[GapOut]
    #: 等待期间仍然可以改需求。这一条要让界面知道，否则它会把这屏做成只读。
    can_still_revise: bool = True


class ProofLineOut(BaseModel):
    text: str
    source: str


class TeamMemberOut(BaseModel):
    principal_id: UUID
    display_name: str


class TeamOut(BaseModel):
    """一个小队。**没有分数，没有百分比**——理由是逐条的。"""

    proposal_id: UUID
    members: list[TeamMemberOut]
    why_these_people: list[ProofLineOut]
    left_to_humans: list[ProofLineOut]
    uncertainties: list[ProofLineOut]
    stability_note: str | None = None
    expires_at: str


class RelaxationOut(BaseModel):
    field_name: str
    invitation: str
    #: 放宽之后多出多少人。真查出来的数字，算不出就是 0，不估。
    gains: int
    advisable: bool
    caution: str = ""


class NextStepOut(BaseModel):
    kind: str
    invitation: str


class BlockedOut(BaseModel):
    """「还差这几件事」那一屏。凑不出队时把挫败换成一个具体的下一步。"""

    stage: str
    statement: str
    causes: list[str]
    relaxations: list[RelaxationOut]
    next_steps: list[NextStepOut]


class GateStatusOut(BaseModel):
    """还在等谁。**已决的折叠起来，这里只出未决的。**"""

    verdict: str
    waiting_on: list[UUID] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    formed_event_id: UUID | None = None
    space_id: UUID | None = None
    #: 有人拒绝之后立刻重解产出了几个新小队。
    #: 界面据此说"有人这次去不了，我又给你找了两组"，
    #: 而不是让发起人对着一句"对方拒绝了"干等到下一个窗口。
    reformed_teams: int = 0


class DecideRequest(BaseModel):
    #: accepted / declined / conditional。**不接受 pending**——
    #: 把答复改回「还没回」没有真实含义。
    answer: str
    condition: str | None = None


class ClearingOut(BaseModel):
    considered: int
    proposed: int
    blocked: int
    early: int


# --- 等配队 ---


@router.get("/me/waiting", response_model=WaitingOut)
def waiting(
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    action_kind: str | None = None,
) -> WaitingOut:
    pulse = MarketBoard(conn, campus, action_kinds).pulse(action_kind, now=clock.now())
    return WaitingOut(
        next_round_at=pulse.next_clearing_at.isoformat(),
        waiting_count=pulse.waiting,
        gaps=[
            GapOut(
                skill=gap.skill,
                wanted=gap.wanted,
                offered=gap.offered,
                scarce=gap.scarce,
            )
            for gap in pulse.gaps
        ],
    )


@router.post("/clearing:run", response_model=ClearingOut)
def run_clearing(conn: ConnDep, campus: CampusDep, clock: ClockDep) -> ClearingOut:
    """把到点的市场单元结算一次。

    它存在是为了让**推进时钟就能看到配队发生**——演示不需要真等六小时。
    重复调用是安全的：同一个窗口内幂等。
    """
    report = Clearing(conn, campus, action_kinds).run(now=clock.now())
    return ClearingOut(
        considered=report.considered,
        proposed=report.proposed,
        blocked=report.blocked,
        early=report.early,
    )


# --- 给你找的人 ---


@router.get("/intents/{intent_id}/teams", response_model=list[TeamOut])
def teams_for(
    intent_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> list[TeamOut]:
    """这条需求配到的小队。

    只给 2–3 个。实证表明选择变多反而降低决策质量——搜索上限 3→100 时
    福利显著下降。多给几个不是慷慨，是把决策成本转嫁给用户。
    """
    intent = repos.intents.get(intent_id)
    if intent is None or intent.principal_id != principal_id:
        # 404 而不是 403：403 等于确认了这个 id 存在。
        raise HTTPException(status_code=404, detail="找不到这条需求")

    rows = ProposalRepository(conn, campus).list_for_intent(
        intent_id, now=clock.now()
    )
    names = _names(repos, rows)
    return [_team(row, names) for row in rows]


@router.get("/intents/{intent_id}/blocked", response_model=BlockedOut)
def blocked_for(
    intent_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> BlockedOut:
    """凑不出队时说什么。

    这一屏最容易被做成一句"暂无结果"，而那正是用户流失的地方。
    """
    intent = repos.intents.get(intent_id)
    if intent is None or intent.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="找不到这条需求")

    kind = action_kinds.get(intent.action_kind) if intent.action_kind else None
    funnel = Funnel(conn, campus)
    trace = funnel.shortlist(intent, now=clock.now()).trace
    proof = explain_recall(funnel, intent, trace.blocked_by, kind=kind)

    return BlockedOut(
        stage=proof.stage.value,
        statement=proof.statement,
        causes=list(proof.causes),
        relaxations=[
            RelaxationOut(
                field_name=r.field_name,
                invitation=r.invitation,
                gains=r.gains,
                advisable=r.advisable,
                caution=r.caution,
            )
            for r in proof.relaxations
        ],
        next_steps=[
            NextStepOut(kind=s.kind.value, invitation=s.invitation)
            for s in proof.next_steps
        ],
    )


# --- 确认门 ---


@router.get("/proposals/{proposal_id}/status", response_model=GateStatusOut)
def gate_status(
    proposal_id: UUID, conn: ConnDep, campus: CampusDep, clock: ClockDep
) -> GateStatusOut:
    try:
        state = ConfirmationGate(conn, campus).status(proposal_id, now=clock.now())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return GateStatusOut(
        verdict=state.verdict.value,
        waiting_on=list(state.waiting_on),
        conditions=[text for _, text in state.conditions],
    )


@router.post("/proposals/{proposal_id}:invite", response_model=GateStatusOut)
def invite(
    proposal_id: UUID, conn: ConnDep, campus: CampusDep, clock: ClockDep
) -> GateStatusOut:
    """给这一版条款的每个成员开一条待答复。重复调用不重置任何人的答复。"""
    gate = ConfirmationGate(conn, campus)
    now = clock.now()
    try:
        gate.invite(proposal_id, now=now)
        state = gate.status(proposal_id, now=now)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return GateStatusOut(verdict=state.verdict.value, waiting_on=list(state.waiting_on))


@router.post("/proposals/{proposal_id}:decide", response_model=GateStatusOut)
def decide(
    proposal_id: UUID,
    payload: DecideRequest,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> GateStatusOut:
    """一个真人做出决定。

    **身份取自请求头，不取自请求体**——请求体里带 principal_id
    等于任何人都能替任何人承诺，而承诺只接受真人签名的命令。
    """
    try:
        answer = CommitmentState(payload.answer)
    except ValueError:
        raise HTTPException(status_code=422, detail="不认识这个答复") from None

    try:
        outcome = ConfirmationGate(conn, campus).decide(
            proposal_id,
            principal_id,
            state=answer,
            now=clock.now(),
            condition=payload.condition,
        )
    except ValueError as exc:
        # 不在名单里、条款已作废、条件没写清——都是 422 而不是 500：
        # 它们是用户能理解并改正的情况，不是服务出错。
        raise HTTPException(status_code=422, detail=str(exc)) from None

    # 有人拒绝就**立刻**用剩下的人重解，不等下一个窗口。
    # 赶截止期的人等不起，而那正是他最需要系统帮忙的时刻。
    reformed = 0
    if outcome.resolve_excluding:
        intent = repos.intents.get(_intent_of(conn, proposal_id))
        if intent is not None:
            reformed = Clearing(conn, campus, action_kinds).resolve_again(
                intent, excluding=outcome.resolve_excluding, now=clock.now()
            )

    return GateStatusOut(
        verdict=outcome.state.verdict.value,
        waiting_on=list(outcome.state.waiting_on),
        conditions=[text for _, text in outcome.state.conditions],
        formed_event_id=outcome.formed.event_id if outcome.formed else None,
        space_id=outcome.formed.space_id if outcome.formed else None,
        reformed_teams=reformed,
    )


# --- 内部 ---


def _intent_of(conn: ConnDep, proposal_id: UUID) -> UUID:
    """这个提案回应的是哪条需求。"""
    return UUID(
        str(
            conn.execute(
                sa.select(formation_proposals.c.intent_id).where(
                    formation_proposals.c.id == proposal_id
                )
            ).scalar_one()
        )
    )


def _names(repos: ReposDep, rows: list[Any]) -> dict[UUID, str]:
    """把 id 换成名字。

    名字不受逐项授权管——同意被放进一个小队，本身就包含了同意在这里被指名，
    否则"为什么是这几个人"整张卡没法呈现。要遮的是切面内容，不是名字。
    """
    ids = {member for row in rows for member in row.member_ids}
    names: dict[UUID, str] = {}
    for principal_id in ids:
        person = repos.principals.get(principal_id)
        if person is not None:
            names[principal_id] = person.display_name
    return names


def _lines(proof: dict[str, Any], key: str) -> list[ProofLineOut]:
    return [
        ProofLineOut(text=str(line.get("text", "")), source=str(line.get("source", "")))
        for line in proof.get(key) or []
        if isinstance(line, dict) and line.get("text")
    ]


def _team(row: Any, names: dict[UUID, str]) -> TeamOut:
    proof: dict[str, Any] = row.proof if isinstance(row.proof, dict) else {}
    stability = proof.get("stability")
    return TeamOut(
        proposal_id=row.id,
        members=[
            TeamMemberOut(
                principal_id=member,
                display_name=names.get(member, "这位同学"),
            )
            for member in row.member_ids
        ],
        why_these_people=_lines(proof, "satisfied"),
        left_to_humans=_lines(proof, "for_humans"),
        uncertainties=_lines(proof, "uncertainties"),
        stability_note=(
            str(stability.get("statement")) if isinstance(stability, dict) else None
        ),
        expires_at=row.expires_at.isoformat(),
    )
