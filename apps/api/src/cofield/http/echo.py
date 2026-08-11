"""这次留下了什么，以及这次你会得到什么。

两屏放在一起，因为它们是同一条闭环的两端：

- **这次你会得到什么** —— 被邀请的一侧看到的。不是"你被选中了"，
  单向推荐会让接收方觉得自己是被挑的商品
- **这次留下了什么** —— 事情做完之后。证据变成一条**要本人点头**的记录，
  点过的那条才会在下一次成局证明里被引用

中间隔着整个产品，但没有这两端，产品只是一个更漂亮的组队工具。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.adapters.llm import Cassette, LiteLLMComposer
from cofield.adapters.persistence.memory import EvidenceItem, MemoryRepository
from cofield.adapters.persistence.schema import (
    event_members,
    formation_proposals,
    shared_events,
)
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep, ReposDep
from cofield.memory.echo import ActionEcho, EchoRefused

router = APIRouter(tags=["echo"])


# --- 这次你会得到什么 ---


class InvitationOut(BaseModel):
    """被邀请的一侧看到的那一屏。

    **不是"你被选中了"。** 单向推荐会让接收方觉得自己是被挑的商品，
    而互惠推荐的成功必须以多方接受为条件——单边相关度会系统性高估
    真实匹配。

    `gets` 为空这一屏就不该存在：说不出对方能得到什么的邀请，
    不该被发出去。
    """

    proposal_id: UUID
    #: 这件事是什么。
    about: str
    #: 一起做这件事的还有谁。
    with_others: list[str]
    #: **我会得到什么。** 这一屏的主语是"我"，不是"他们需要你"。
    i_get: list[str]
    #: 我要出的。放在得到之后——先说代价的邀请没人会读完。
    i_give: list[str]
    #: 大概要花多少时间。说不清就说不清，不编。
    time_cost: str | None = None
    #: 到什么时候要答复。
    answer_by: str


@router.get("/proposals/{proposal_id}/invitation", response_model=InvitationOut)
def invitation(
    proposal_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> InvitationOut:
    """我被邀请进了这一队，这次我会得到什么。

    只有名单上的人看得到。不在名单上返回 404 而不是 403——
    403 等于确认了这个提案存在。
    """
    row = conn.execute(
        sa.select(formation_proposals).where(formation_proposals.c.id == proposal_id)
    ).one_or_none()
    if row is None or principal_id not in set(row.member_ids):
        raise HTTPException(status_code=404, detail="找不到这个邀请")

    intent = repos.intents.get(row.intent_id)
    others = [
        person.display_name
        for member_id in row.member_ids
        if member_id != principal_id
        and (person := repos.principals.get(member_id)) is not None
    ]

    me = repos.principals.get(principal_id)
    my_skills = frozenset(getattr(me, "skills", ()) or ())
    needs = frozenset(intent.content.needs) if intent else frozenset()

    # 我会得到什么：这件事本身，加上别人带来的、我没有的本事。
    # **不写"提升自己""拓展人脉"这类话**——它们对谁都成立，因而对谁都没用。
    gets: list[str] = []
    if intent:
        gets.append(f"一起做成「{intent.content.goal}」，这件事会留在你的记录里")
    brought = sorted(
        skill
        for member_id in row.member_ids
        if member_id != principal_id
        for skill in (getattr(repos.principals.get(member_id), "skills", ()) or ())
        if skill not in my_skills
    )
    if brought:
        gets.append("同队的人会「" + "、".join(brought[:3]) + "」，你不用自己扛")

    gives = sorted(my_skills & needs)

    return InvitationOut(
        proposal_id=proposal_id,
        about=intent.content.goal if intent else "一件事",
        with_others=others,
        i_get=gets,
        i_give=[f"你的「{skill}」" for skill in gives],
        time_cost=None,
        answer_by=row.expires_at.isoformat(),
    )


# --- 这次留下了什么 ---


class EvidenceIn(BaseModel):
    #: photo / note / artifact / link
    kind: str = "note"
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    uri: str | None = None


class EvidenceOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    uri: str | None
    uploaded_by: UUID


class RecapOut(BaseModel):
    """这次一起做成了什么。

    **不入库。** 它是证据的一次转写，删掉重算还是它；存下来只会多一份
    可能和证据不一致的副本。要留下来的东西是那条记录，而那个要本人点头。
    """

    text: str
    grounded_in: list[str]


class DraftOut(BaseModel):
    facet_id: UUID
    text: str
    grounded_in: list[str]
    #: 常驻的那句话。草稿和已确认的内容必须**一眼可辨**，
    #: 而"一眼"的意思是它自己带着这句话，不靠界面记得加角标。
    hint: str
    drafted_by_agent: bool


class EchoOut(BaseModel):
    event_title: str
    evidence: list[EvidenceOut]
    recap: RecapOut | None = None
    #: 等我点头的。**没点过的永远不出现在任何人的证明里。**
    to_confirm: list[DraftOut] = Field(default_factory=list)


class WriteOwnIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


def _must_be_member(conn: ConnDep, event_id: UUID, principal_id: UUID) -> str:
    """这件事必须是我参加过的。

    404 而不是 403：403 等于确认了这个事件存在。
    """
    title = conn.execute(
        sa.select(shared_events.c.title).where(shared_events.c.id == event_id)
    ).scalar_one_or_none()
    mine = conn.execute(
        sa.select(sa.literal(1))
        .select_from(event_members)
        .where(event_members.c.event_id == event_id)
        .where(event_members.c.principal_id == principal_id)
        .limit(1)
    ).first()
    if title is None or mine is None:
        raise HTTPException(status_code=404, detail="找不到这件事")
    return str(title)


@router.post(
    "/events/{event_id}/evidence", response_model=EvidenceOut, status_code=201
)
def add_evidence(
    event_id: UUID,
    payload: EvidenceIn,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    principal_id: PrincipalDep,
) -> EvidenceOut:
    """留下一件东西：返图、一段记录、做出来的成果。

    **只存事实不存评价。** 这里没有任何字段能放"谁表现好"，表里也没有——
    不是暂时没实现，是它不该存在。一旦开始存，它就变成打分系统，
    而打分系统会让人不敢参加自己不擅长的事。
    """
    _must_be_member(conn, event_id, principal_id)
    item = EvidenceItem(
        id=uuid4(),
        event_id=event_id,
        kind=payload.kind,
        title=payload.title,
        uploaded_by=principal_id,
        created_at=clock.now(),
        body=payload.body,
        uri=payload.uri,
    )
    MemoryRepository(conn, campus).add_evidence(item)
    return EvidenceOut(
        id=item.id,
        kind=item.kind,
        title=item.title,
        body=item.body,
        uri=item.uri,
        uploaded_by=item.uploaded_by,
    )


@router.get("/events/{event_id}/echo", response_model=EchoOut)
def echo(
    event_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    principal_id: PrincipalDep,
) -> EchoOut:
    """这件事结束之后的那一屏。

    抽不出草稿**不是错误**：这次没证据就没什么可抽的，起草服务挂了就闭嘴。
    两种情况下这一屏都照常——用户仍然能看证据、能自己写一条。
    """
    title = _must_be_member(conn, event_id, principal_id)
    repo = MemoryRepository(conn, campus)
    action = ActionEcho(repo, composer=Cassette(LiteLLMComposer()))

    evidence = [
        EvidenceOut(
            id=item.id,
            kind=item.kind,
            title=item.title,
            body=item.body,
            uri=item.uri,
            uploaded_by=item.uploaded_by,
        )
        for item in action.gather(event_id)
    ]
    recap = action.recap(event_id)
    drafts = action.draft_for(
        event_id=event_id, principal_id=principal_id, now=clock.now()
    )

    return EchoOut(
        event_title=title,
        evidence=evidence,
        recap=(
            RecapOut(text=recap.text, grounded_in=list(recap.grounded_in))
            if recap
            else None
        ),
        to_confirm=[
            DraftOut(
                facet_id=d.facet.id,
                text=d.facet.text,
                grounded_in=list(d.grounded_in),
                hint=d.hint,
                drafted_by_agent=d.facet.drafted_by_agent,
            )
            for d in drafts
        ],
    )


@router.post("/events/{event_id}/records", response_model=DraftOut, status_code=201)
def write_own(
    event_id: UUID,
    payload: WriteOwnIn,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    principal_id: PrincipalDep,
) -> DraftOut:
    """自己写一条。

    它同样落成草稿，同样要再点一次确认。看起来多此一举——本人写的东西
    为什么还要本人再点？因为**只留一条通往「算数」的路**：两条路意味着
    "哪些记录算数"这个问题有两个答案。
    """
    _must_be_member(conn, event_id, principal_id)
    repo = MemoryRepository(conn, campus)
    action = ActionEcho(repo, composer=Cassette(LiteLLMComposer()))
    try:
        facet = action.write_own(
            principal_id=principal_id,
            text=payload.text,
            now=clock.now(),
            event_id=event_id,
        )
    except EchoRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    return DraftOut(
        facet_id=facet.id,
        text=facet.text,
        grounded_in=[],
        hint="这是你自己写的，点一下才会开始被用到。",
        drafted_by_agent=False,
    )


@router.get("/me/proposals", response_model=list[UUID])
def my_invitations(
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    principal_id: PrincipalDep,
) -> list[UUID]:
    """我被邀请进了哪几队。

    界面靠它把「这次你会得到什么」那一屏找出来——否则被邀请的人
    根本不知道有人在等他答复。
    """
    rows = conn.execute(
        sa.select(formation_proposals.c.id)
        .where(formation_proposals.c.member_ids.any(principal_id))
        .where(formation_proposals.c.withdrawn_at.is_(None))
        .where(formation_proposals.c.expires_at > clock.now())
        .order_by(formation_proposals.c.cleared_at.desc())
    ).all()
    return [row.id for row in rows]

