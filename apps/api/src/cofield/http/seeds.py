"""投递制：信箱、表态、挑人。

## 这一屏解决的是「石沉大海」

旧链路让发起人**把勇气花在一次抛硬币上**——挑一支队，然后等对方理不理你。
而"石沉大海"正是这个产品要消灭的第二个痛点（ADR 0010）。

现在：种子投给多个候选 → 候选各自表态 → 发起人**在已经说了愿意的人里**挑，
挑到种子要的人数收满为止。**他面对的每一个人都已经说过愿意。**

## 三条产品规则

**不向候选展示排名、竞争人数或最终被选者。** 他只需要知道这件事是什么、
为什么找到他、愿不愿意参与。知道自己是第几名只会让人退出。

**拒绝文案不表达"你不合适"。** 说的是「这颗种子已经找到同行者」——
那是种子的处境，不是对他的评价，而这里没有评价。

**AI 不替发起人做最终选择。** 它排序、它解释，但那一下必须是人点的。
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid5

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cofield.adapters.persistence.deliveries import Delivered, DeliveryRepository
from cofield.adapters.persistence.events import EventRepository
from cofield.domain.model.intent import IntentState
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep, ReposDep

router = APIRouter(tags=["seeds"])

#: 由需求 id 派生事件 id 的命名空间。
#:
#: 事件表上「一个提案最多变成一个事件」那条唯一约束因此变成
#: **一条需求最多成一件事**——投递制下没有提案，但那条约束要守的东西
#: （重复确认不产生第二个事件）一模一样。
_EVENT_NS = UUID("6f1f0f7a-2f5e-4a19-9b3b-1f6b2a7c0d11")


class SeedOut(BaseModel):
    """信箱里的一颗种子。

    **完整展示行动信息，有限展示发起人信息**（PRD 阶段三）：他要判断的是
    这件事值不值得参与，不是这个人够不够格。
    """

    intent_id: UUID
    goal: str
    #: 原话。结构化装不下的那半句留在这里。
    said: str
    needs: list[str]
    offers: list[str]
    when: str | None = None
    where: str | None = None
    team_min: int | None = None
    team_max: int | None = None
    from_name: str
    #: 为什么找到你。逐条可追溯，不含分数也不含相似度。
    why: list[str]
    #: delivered / willing / passed / chosen
    state: str
    my_note: str | None = None
    #: 被挑中之后，这件事在哪。
    #:
    #: **不能把他丢到别处让他自己找。** 他刚被选中，最想去的是那件事本身；
    #: 多一步"自己找"，那一下的兴奋就被磨掉了。
    space_id: UUID | None = None


class RespondRequest(BaseModel):
    #: 愿意参与，还是这次不感兴趣。
    willing: bool
    #: 说一句话。**可选**——要求写理由会让人不敢点愿意。
    note: str | None = Field(default=None, max_length=200)
    #: 「这次不行，以后类似的叫我」。
    #:
    #: **不是第四种表态**，是不感兴趣 + 留下一条线索：把这件事缺的那几样
    #: 加进我的「我想参与的」，下次有人缺同样的东西时我会出现在候选里。
    remind_me: bool = False


class CandidateOut(BaseModel):
    """一个说了愿意的人。"""

    principal_id: UUID
    display_name: str
    why: list[str]
    note: str | None = None
    chosen: bool = False


class CandidatesOut(BaseModel):
    """发起人那一屏。

    **不给分数。** AI 排序并解释，但最后那一下必须是人点的。
    """

    still_need: int
    chosen: list[CandidateOut]
    willing: list[CandidateOut]
    #: 已经投出去还没答的人数。**只给数量不给名字**——
    #: 没答的人不该因为"还没答"就被指名。
    still_thinking: int
    formed_event_id: UUID | None = None
    space_id: UUID | None = None


@router.get("/me/seeds", response_model=list[SeedOut])
def my_seeds(
    conn: ConnDep, campus: CampusDep, repos: ReposDep, principal_id: PrincipalDep
) -> list[SeedOut]:
    """我的信箱。已经找到同行者的种子不再占地方。"""
    rows = DeliveryRepository(conn, campus).inbox(principal_id)
    out: list[SeedOut] = []
    for row in rows:
        intent = repos.intents.get(row.intent_id)
        if intent is None:
            continue
        who = repos.principals.get(intent.principal_id)
        content = intent.content
        out.append(
            SeedOut(
                intent_id=intent.id,
                goal=content.goal,
                said=intent.raw_expression,
                needs=list(content.needs),
                offers=list(content.offers),
                when=(
                    content.time_window.deadline.isoformat()
                    if content.time_window and content.time_window.deadline
                    else None
                ),
                where=content.location_scope,
                team_min=content.team_size.minimum if content.team_size else None,
                team_max=content.team_size.maximum if content.team_size else None,
                from_name=who.display_name if who else "一个同学",
                why=list(row.why),
                state=row.state.value,
                my_note=row.note,
                space_id=(
                    formed[1]
                    if row.state is Delivered.CHOSEN
                    and (formed := EventRepository(conn, campus).formed_from(
                        uuid5(_EVENT_NS, str(intent.id))
                    ))
                    else None
                ),
            )
        )
    return out


@router.post("/seeds/{intent_id}:respond", response_model=SeedOut)
def respond(
    intent_id: UUID,
    payload: RespondRequest,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> SeedOut:
    """愿意参与，或者这次不感兴趣。

    **愿意不等于加入**：还要发起人挑中才成局。这一句必须在界面上说清楚，
    否则用户会以为自己已经答应了，然后在没被选中时觉得被放了鸽子。
    """
    answered = DeliveryRepository(conn, campus).answer(
        intent_id,
        by=principal_id,
        willing=payload.willing,
        note=payload.note,
        now=clock.now(),
    )
    if answered is None:
        # 已经答过了，或者这颗种子根本没投给他。两种都回同一句：
        # 区分它们等于告诉他"有一颗种子存在但不是给你的"。
        raise HTTPException(status_code=404, detail="这颗种子现在不在你这里")

    if payload.remind_me and not payload.willing:
        # 只在不感兴趣时有意义：愿意了就不需要"以后再叫我"。
        intent = repos.intents.get(intent_id)
        if intent is not None:
            me = repos.principals.get(principal_id)
            wanted = [
                need
                for need in intent.content.needs
                if me is None or need not in me.open_to
            ]
            repos.principals.remind_about(principal_id, wanted)

    mine = [s for s in my_seeds(conn, campus, repos, principal_id) if s.intent_id == intent_id]
    if mine:
        return mine[0]
    # 说了不感兴趣之后它就不在信箱里了——照样把这一次的结果回给界面。
    intent = repos.intents.get(intent_id)
    assert intent is not None  # noqa: S101
    return SeedOut(
        intent_id=intent_id,
        goal=intent.content.goal,
        said=intent.raw_expression,
        needs=list(intent.content.needs),
        offers=list(intent.content.offers),
        from_name="",
        why=list(answered.why),
        state=answered.state.value,
        my_note=answered.note,
    )


@router.get("/intents/{intent_id}/candidates", response_model=CandidatesOut)
def candidates(
    intent_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> CandidatesOut:
    """谁说了愿意。发起人在这一屏挑人。"""
    intent = repos.intents.get(intent_id)
    if intent is None or intent.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    return _screen(conn, campus, repos, intent_id, intent)


@router.post(
    "/intents/{intent_id}/candidates/{who}:choose", response_model=CandidatesOut
)
def choose(
    intent_id: UUID,
    who: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> CandidatesOut:
    """挑一个人。收满就成局。

    **AI 不替发起人做这一下。** 它排序、它解释，但按下去的必须是人。
    """
    intent = repos.intents.get(intent_id)
    if intent is None or intent.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="找不到这条需求")

    deliveries = DeliveryRepository(conn, campus)
    if deliveries.choose(intent_id, who=who, now=clock.now()) is None:
        raise HTTPException(status_code=422, detail="他还没说愿意，或者已经选过了")

    picked = deliveries.chosen(intent_id)
    size = intent.content.team_size
    need = (size.minimum if size else 2) - 1
    if len(picked) >= need:
        # 收满了：成局，其余的关掉。
        #
        # 两边都动过手——候选说了愿意，发起人挑了他——所以这一刻**双方
        # 都确认过**，满足不变量 3（真人确认后才创建共同事件与共域）。
        events = EventRepository(conn, campus)
        events.form(
            proposal_id=uuid5(_EVENT_NS, str(intent_id)),
            action_kind=intent.action_kind,
            title=intent.content.goal or "我们的项目",
            goal=intent.content.goal,
            steward_id=intent.principal_id,
            member_ids=(intent.principal_id, *picked),
            role_assignment={},
            deadline=(
                intent.content.time_window.deadline
                if intent.content.time_window
                else None
            ),
            first_action=None,
            now=clock.now(),
        )
        deliveries.close_rest(intent_id)
        # 这条需求不再进池子：它已经成了。
        repos.intents.save(replace(intent, state=IntentState.MATCHED))

    return _screen(conn, campus, repos, intent_id, intent)


def _screen(
    conn: ConnDep, campus: str, repos: ReposDep, intent_id: UUID, intent: object
) -> CandidatesOut:
    deliveries = DeliveryRepository(conn, campus)
    rows = deliveries.for_intent(intent_id)
    names = {
        r.principal_id: (
            p.display_name if (p := repos.principals.get(r.principal_id)) else "一个同学"
        )
        for r in rows
    }

    def card(row: object, chosen: bool) -> CandidateOut:
        return CandidateOut(
            principal_id=row.principal_id,  # type: ignore[attr-defined]
            display_name=names.get(row.principal_id, "一个同学"),  # type: ignore[attr-defined]
            why=list(row.why),  # type: ignore[attr-defined]
            note=row.note,  # type: ignore[attr-defined]
            chosen=chosen,
        )

    picked = [r for r in rows if r.state is Delivered.CHOSEN]
    willing = [r for r in rows if r.state is Delivered.WILLING]
    size = intent.content.team_size  # type: ignore[attr-defined]
    need = (size.minimum if size else 2) - 1

    formed = EventRepository(conn, campus).formed_from(uuid5(_EVENT_NS, str(intent_id)))
    return CandidatesOut(
        still_need=max(0, need - len(picked)),
        chosen=[card(r, True) for r in picked],
        willing=[card(r, False) for r in willing],
        still_thinking=sum(1 for r in rows if r.state is Delivered.DELIVERED),
        formed_event_id=formed[0] if formed else None,
        space_id=formed[1] if formed else None,
    )


__all__ = ["router"]
