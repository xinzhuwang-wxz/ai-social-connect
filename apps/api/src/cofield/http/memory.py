"""三个自我管理面：我参加过的 / 关于我的记录 / 谁能看到我。

## 为什么全部挂在 `/me` 下

**系统里不存在供他人浏览的个人主页端点。** 一旦出现
`/principals/{id}/facets` 这样的路径，两件事同时发生：任何人都能看任何人；
产品退回「看人卡决定要不要连接」，而那样冷启动用户天然吃亏。别人永远只
看到「针对某一次成局、经本人同意的那个切片」——那条路走的是成局证明，
不走这里。所以这三个面的身份一律来自 `PrincipalDep`，不来自路径参数，
也不来自请求体。

## 三个面都是读模型，不新增任何聚合根

- 我参加过的 ← `event_members` ⋈ `shared_events`
- 关于我的记录 ← `memory_facets`（+ `evidence` 指回来源）
- 谁能看到我 ← `match_envelopes`（+ `intent_signals` 说清是给哪件事的）

写操作只有两个，而且都是**已有**的领域命令：本人确认、本人收回。
收回一次对外披露走的是既有的 `POST /envelopes/{id}:revoke`——
这一面不重新实现一遍撤销，两条写路径迟早会不一致。

## 「收回即时生效」靠的是没有副本

`MemoryRepository.citable()` 是切面被引用的唯一入口，它在 WHERE 里写死
`state = 'confirmed' AND revoked_at IS NULL`。所以「谁能看到我」列出的
记录原话也走 `citable()`，「关于我的记录」的 `in_use` 同样走它——
这一面**刻意不自己拼 SQL 去取切面文本**，就是为了不制造第二份会变旧的
副本。收回之后下一次查询必然读不到，不是"标记为已删除但还在用"。

界面文案不使用领域词汇（见 docs/07 语言映射表）；字段名用领域词汇，
两者是两套东西（docs/08 §1 第三条）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from cofield.adapters.persistence.memory import (
    FacetState,
    MemoryFacet,
    MemoryRepository,
)
from cofield.adapters.persistence.schema import (
    action_plans,
    day_of_states,
    event_members,
    evidence,
    intent_signals,
    plan_nods,
    principals,
    shared_events,
    space_items,
    spaces,
)
from cofield.catalog import registry as action_kinds
from cofield.domain.model import growth
from cofield.domain.model.consent import Audience, MatchEnvelope
from cofield.domain.model.skills import SKILLS, normalise
from cofield.http.deps import CampusDep, ClockDep, ConnDep, PrincipalDep, ReposDep
from cofield.matching.window import Clearing

router = APIRouter(tags=["memory"])


# --- 响应形状 ---


class MemberOut(BaseModel):
    """上次一起做这件事的一个人。"""

    principal_id: UUID
    display_name: str


class MyEventOut(BaseModel):
    """一次做成的事，不是一个头衔。

    取消的事照样在这里——它属于本人的真实经历，藏起来就等于系统替他
    修饰了历史。但它**不产生成功记录**，所以 `counts_as_done` 是独立字段
    而不是让界面自己从 `state` 推：推错了就会把没做成的事说成做成了。
    """

    event_id: UUID
    title: str
    goal: str
    #: active / completed / abandoned。界面自己翻成人话。
    state: str
    formed_at: datetime
    deadline: datetime | None = None
    #: 中途退出的时刻。非空表示这件事我没走到最后。
    left_at: datetime | None = None
    #: 一起做这件事的人。名字不受逐项同意管——同意进一个小队本身就包含了
    #: 同意在这里被指名，否则「和谁做的」根本没法呈现。
    with_others: list[str]
    counts_as_done: bool
    #: 长到哪一步了。**派生值**——由可查的事实定档，不由聊天量定档。
    #: 「我的森林」里一件事一株，靠它决定长什么样。
    growth: str
    growth_word: str
    #: 这件事的空间。**没有它「我参加过的」就走不到项目空间**——
    #: 而那是这个产品里唯一能继续做事的地方。
    space_id: UUID | None = None


class RecordSourceOut(BaseModel):
    """一条记录指回去的那件东西。"""

    evidence_id: UUID
    #: photo / note / artifact / link
    kind: str
    title: str
    added_at: datetime


class MyRecordOut(BaseModel):
    """系统记着的、关于我的一句话。

    三样东西缺一不可：说了什么、从哪来的、谁写的。说不出来源的记录，
    本人无从判断该不该留着它；看不出是谁写的，"AI 起草、人类决定"
    就只是一句话。
    """

    id: UUID
    text: str
    #: draft / confirmed / revoked
    state: str
    #: 是不是系统猜的。界面据此给它一条独立的视觉通道。
    drafted_by_agent: bool
    created_at: datetime
    confirmed_at: datetime | None = None
    revoked_at: datetime | None = None
    event_id: UUID | None = None
    #: 这条是哪件事留下的。事件已经不在了就是 None，界面照常显示这条记录。
    event_title: str | None = None
    sources: list[RecordSourceOut]
    #: 现在有几处正在用它。**收回之后立刻是 0**——它走的是 `citable()`，
    #: 不是数一数有多少地方列过这个 id。
    in_use: int


class MyRecordsOut(BaseModel):
    """待确认的和已确认的**分开返回**，不是一个列表加一个状态字段。

    分组在服务端做，界面就没有把两堆混起来显示的机会——而"没点过的
    永远不出现在任何人的证明里"这条，恰恰最怕的就是混起来。

    收回过的也列出来：本人要看得见系统猜过什么、自己点过什么、
    又收回过什么，只给已确认的那部分，"系统记住了什么"就永远答不完整。
    """

    to_confirm: list[MyRecordOut]
    confirmed: list[MyRecordOut]
    revoked: list[MyRecordOut]


class ShownFieldOut(BaseModel):
    """这次带出去的一项。

    `field_name` 是标识符，界面把它翻成人话——服务端不发中文标签，
    是为了不让同一个字段的说法在两个屏上各存一份、迟早对不上。
    """

    field_name: str
    #: false = 只用来配队，对方看不到。少了这一档，用户只能在
    #: "完全不给"和"给所有人看"之间二选一。
    seen_by_others: bool


class VisibilityOut(BaseModel):
    """一次仍在生效的对外披露。

    `for_what` 不是装饰：一排"3 项，72 小时后失效"用户分辨不出哪条是哪条，
    也就没法决定收回哪一条。收不回的权利等于没有这项权利。
    """

    envelope_id: UUID
    intent_id: UUID
    for_what: str
    shows: list[ShownFieldOut]
    #: 这次带出去的、我自己那几句话的原文。**已经收回的不会出现在这里。**
    shows_records: list[str]
    expires_at: datetime


# --- 我参加过的 ---


@router.get("/me/events", response_model=list[MyEventOut])
def my_events(conn: ConnDep, principal_id: PrincipalDep) -> list[MyEventOut]:
    """我参加过的事，进行中、已完成、已取消都在。

    空列表不是错误：一个刚注册的人本来就什么都没参加过，
    这一屏该说的是"先说说想做点什么"，不是 404。
    """
    rows = conn.execute(
        sa.select(
            shared_events.c.id,
            shared_events.c.title,
            shared_events.c.goal,
            shared_events.c.state,
            shared_events.c.formed_at,
            shared_events.c.deadline,
            event_members.c.left_at,
            spaces.c.id.label("space_id"),
        )
        .select_from(
            event_members.join(
                shared_events, shared_events.c.id == event_members.c.event_id
            ).outerjoin(spaces, spaces.c.event_id == shared_events.c.id)
        )
        .where(event_members.c.principal_id == principal_id)
        .order_by(shared_events.c.formed_at.desc(), shared_events.c.id.asc())
    ).all()

    others = _companions(conn, [r.id for r in rows], principal_id)
    stages = _stages(conn, rows)
    return [
        MyEventOut(
            event_id=r.id,
            title=r.title,
            goal=r.goal,
            state=r.state,
            formed_at=r.formed_at,
            deadline=r.deadline,
            left_at=r.left_at,
            with_others=others.get(r.id, []),
            # 中途退出的事仍然是我的经历，但"我们一起做完过"这句话对我不成立。
            # 这和 `MemoryRepository.co_completed()` 的 `left_at IS NULL` 是同一个判断。
            counts_as_done=r.state == "completed" and r.left_at is None,
            space_id=r.space_id,
            growth=stages[r.id].stage.value,
            growth_word=stages[r.id].word,
        )
        for r in rows
    ]


def _stages(
    conn: Connection, rows: Sequence[sa.Row[tuple[object, ...]]]
) -> dict[UUID, growth.Growth]:
    """每件事长到哪一步了。

    **一次查完，不逐件问。** 「我的森林」上可能有几十株，一株一次查询就是
    几十次往返，而这一屏的全部意义正是"一眼看完自己做过什么"。

    判据和共域那一屏完全一样（见 `http/spaces._growth_of`）：
    计划确认了结花苞，全员点完成开花——**不看聊天量**（不变量 6）。
    """
    ids = [r.space_id for r in rows if r.space_id is not None]
    if not ids:
        return {r.id: growth.of(
            formed=True,
            has_claimed_items=False,
            plan_confirmed=False,
            completed=False,
            has_evidence=False,
        ) for r in rows}

    confirmed = {
        row.space_id
        for row in conn.execute(
            sa.select(action_plans.c.space_id)
            .select_from(
                action_plans.join(
                    plan_nods,
                    sa.and_(
                        plan_nods.c.plan_id == action_plans.c.id,
                        plan_nods.c.digest == action_plans.c.digest,
                    ),
                )
            )
            .where(action_plans.c.space_id.in_(ids))
            .where(action_plans.c.starts_at.isnot(None))
        ).all()
    }
    claimed = {
        row.space_id
        for row in conn.execute(
            sa.select(space_items.c.space_id)
            .where(space_items.c.space_id.in_(ids))
            .where(space_items.c.assignee_id.isnot(None))
        ).all()
    }
    return {
        r.id: growth.of(
            formed=True,
            has_claimed_items=r.space_id in claimed,
            plan_confirmed=r.space_id in confirmed,
            completed=r.state == "completed" and r.left_at is None,
            has_evidence=r.state == "completed" and r.left_at is None,
        )
        for r in rows
    }


class AgainOut(BaseModel):
    """照上次再来一次：一张**还没保存**的草稿。

    PRD 的最后一段（持续互动）。第一次行动完成后产品进入下一轮 Loop——
    而在这之前，森林里的一株点进去只能看。

    **它不直接建需求。** 抽取只产出草稿这条规矩在这里同样成立：
    带过来的东西要让本人过目，尤其是时间和地点——它们必然是新的。
    """

    goal: str
    offers: list[str]
    needs: list[str]
    team_min: int | None = None
    team_max: int | None = None
    #: 上次一起做这件事的人。**默认不勾**——上次合得来不等于这次还想找他，
    #: 而替他勾上等于替他决定了要不要再叫这些人。
    last_time_with: list[MemberOut] = Field(default_factory=list)


class AgainRequest(BaseModel):
    #: 这条新需求的 id。它必须已经确认过——没确认的需求不该被拿去问人。
    intent_id: UUID
    #: 要问的那几个人。空就只是普通地进池子等配队。
    invite: list[UUID] = Field(default_factory=list)


@router.get("/events/{event_id}/again", response_model=AgainOut)
def again(
    event_id: UUID, conn: ConnDep, repos: ReposDep, principal_id: PrincipalDep
) -> AgainOut:
    """照这件事再来一次，先给一张草稿。"""
    row = conn.execute(
        sa.select(shared_events.c.title, shared_events.c.goal)
        .select_from(
            shared_events.join(
                event_members, event_members.c.event_id == shared_events.c.id
            )
        )
        .where(shared_events.c.id == event_id)
        .where(event_members.c.principal_id == principal_id)
    ).one_or_none()
    if row is None:
        # 404 而不是 403：403 等于确认了这个 id 存在。
        raise HTTPException(status_code=404, detail="找不到这件事")

    others = conn.execute(
        sa.select(event_members.c.principal_id, principals.c.display_name)
        .select_from(
            event_members.join(
                principals, principals.c.id == event_members.c.principal_id
            )
        )
        .where(event_members.c.event_id == event_id)
        .where(event_members.c.principal_id != principal_id)
    ).all()

    mine = repos.principals.get(principal_id)
    return AgainOut(
        goal=row.goal or row.title,
        offers=list(mine.skills) if mine else [],
        # 缺什么由本人重填：上次缺的这次未必缺，而带过来一个错的比空着糟。
        needs=[],
        team_min=len(others) + 1,
        team_max=len(others) + 1,
        last_time_with=[
            MemberOut(principal_id=r.principal_id, display_name=r.display_name)
            for r in others
        ],
    )


@router.post("/events/{event_id}:again", response_model=dict[str, int])
def ask_them_again(
    event_id: UUID,
    payload: AgainRequest,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> dict[str, int]:
    """把这条新需求直接问上次那几个人。

    **不是把他们拉进来。** 不变量 3：成局前只有提案，没有关系——所以这里
    产出的仍然是一个要每个人各自点头的提案。"一键重新邀请"指的是
    "一键问他们"，不是"一键把他们算进去"。

    仍然过求解器和稳定性检查：上次一起做成过，不等于这次这几个人凑得成
    一个组。跳过这两步等于给他们一个看起来成立、实际不成立的提案。
    """
    intent = repos.intents.get(payload.intent_id)
    if intent is None or intent.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    if not intent.is_matchable:
        raise HTTPException(status_code=422, detail="这条还没确认，先确认再问人")

    was_member = conn.execute(
        sa.select(event_members.c.principal_id)
        .where(event_members.c.event_id == event_id)
        .where(event_members.c.principal_id == principal_id)
    ).one_or_none()
    if was_member is None:
        raise HTTPException(status_code=404, detail="找不到这件事")

    made = Clearing(conn, campus, action_kinds).propose_to(
        intent, people=payload.invite, now=clock.now()
    )
    return {"asked": made}


class ComingUpOut(BaseModel):
    """明天要出发的事。

    ## 为什么是拉不是推

    `lib/inbox.ts` 里已经有过同一个判断，照它：推送要设备权限、要服务端
    订阅、要一套退订，而这里真正要解决的问题只是**"他不知道"**。
    一个常驻的入口就够了。

    等真的有人说"看到得太晚"再上推送——反过来先上推送，是为一个还没被
    验证的问题付一整套代价。
    """

    event_id: UUID
    space_id: UUID | None = None
    title: str
    starts_at: str
    where: str | None = None
    bring: str | None = None
    change_note: str | None = None
    #: 我已经说过自己什么状态了没有。说过就不该再被当成"还没准备"催。
    my_state: str | None = None


@router.get("/me/coming-up", response_model=list[ComingUpOut])
def coming_up(
    conn: ConnDep, campus: CampusDep, clock: ClockDep, principal_id: PrincipalDep
) -> list[ComingUpOut]:
    """我这两天要出发的事。

    只看**已经定下来时间**的（行动确认卡写了 `starts_at`）。没定时间的事
    不该出现在这里——它不是"快到了"，它是"还没定"，而那一句在别处说。

    窗口是从现在到 36 小时后：够覆盖"明天出发"，又不会把下周的事提前
    塞进来。提前太多的提醒和不提醒一样，人会学会忽略它。
    """
    now = clock.now()
    rows = conn.execute(
        sa.select(
            shared_events.c.id.label("event_id"),
            shared_events.c.title,
            spaces.c.id.label("space_id"),
            action_plans.c.title.label("plan_title"),
            action_plans.c.starts_at,
            action_plans.c.place,
            action_plans.c.bring,
            action_plans.c.change_note,
            day_of_states.c.state.label("my_state"),
        )
        .select_from(
            event_members.join(
                shared_events, shared_events.c.id == event_members.c.event_id
            )
            .join(spaces, spaces.c.event_id == shared_events.c.id)
            .join(action_plans, action_plans.c.space_id == spaces.c.id)
            .outerjoin(
                day_of_states,
                sa.and_(
                    day_of_states.c.space_id == spaces.c.id,
                    day_of_states.c.principal_id == principal_id,
                ),
            )
        )
        .where(event_members.c.principal_id == principal_id)
        .where(event_members.c.left_at.is_(None))
        .where(shared_events.c.state == "active")
        .where(action_plans.c.starts_at.isnot(None))
        .where(action_plans.c.starts_at > now - timedelta(hours=6))
        .where(action_plans.c.starts_at < now + timedelta(hours=36))
        .order_by(action_plans.c.starts_at.asc())
    ).all()

    return [
        ComingUpOut(
            event_id=r.event_id,
            space_id=r.space_id,
            title=r.plan_title or r.title,
            starts_at=r.starts_at.isoformat(),
            where=r.place,
            bring=r.bring,
            change_note=r.change_note,
            my_state=r.my_state,
        )
        for r in rows
    ]


# --- 关于我的记录 ---


@router.get("/me/facets", response_model=MyRecordsOut)
def my_records(
    conn: ConnDep,
    campus: CampusDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> MyRecordsOut:
    """系统记着的关于我的每一句话，按处境分三堆。"""
    memory = MemoryRepository(conn, campus)
    facets = memory.for_principal(principal_id)
    cards = _cards(conn, memory, facets, principal_id, repos)
    by_state = {f.id: f.state for f in facets}
    return MyRecordsOut(
        to_confirm=[c for c in cards if by_state[c.id] is FacetState.DRAFT],
        confirmed=[c for c in cards if by_state[c.id] is FacetState.CONFIRMED],
        revoked=[c for c in cards if by_state[c.id] is FacetState.REVOKED],
    )


@router.post("/facets/{facet_id}:confirm", response_model=MyRecordOut)
def confirm_record(
    facet_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> MyRecordOut:
    """本人点头。只有点过头的那些能被引用。

    仓储把 `principal_id = by` 写在 WHERE 里，所以"只能确认自己的"
    在 SQL 层就成立；这里再查一次是为了给出**说得清的失败**，
    不是为了做权限判断。
    """
    memory = MemoryRepository(conn, campus)
    current = _mine(memory, facet_id, principal_id)
    if current.state is FacetState.REVOKED:
        # 收回就是收回，没有回到"已确认"的路径。少了这一条，
        # 撤销就退化成"暂时不用"。
        raise HTTPException(status_code=422, detail="这条你已经收回了，不会再用它")

    # 已经确认过的重复点一次不算错，返回它现在的样子——
    # 重复点击报错只会让人以为自己弄坏了什么。
    updated = memory.confirm(facet_id, by=principal_id, now=clock.now()) or current

    # **他点头承认的这句话，如果说到一样本事，那就是他会的。**
    #
    # 这是"一个人由什么表达"的第三条来源，也是唯一一条来自**做过的事**
    # 而不是说过的话的：他做完一件事，系统从留下的东西里写出一句
    # 「这次的片子是他剪的」，他看过、点了头——到这一步，"会剪辑"已经
    # 比任何一张勾选表都更实在。
    #
    # 只在**本人确认之后**才回流。系统猜的那一版（draft）什么都不算，
    # 这正是猜和事实之间那道门存在的意义。
    if updated.citable:
        repos.principals.learned(
            principal_id,
            [
                skill
                for skill in SKILLS
                if skill in updated.text and normalise(skill) is not None
            ],
        )
    return _one(conn, memory, updated, principal_id, repos)


@router.post("/facets/{facet_id}:revoke", response_model=MyRecordOut)
def revoke_record(
    facet_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    clock: ClockDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> MyRecordOut:
    """本人收回。一步完成，不问为什么，不再确认一次。

    收回一条记录应该像删一条朋友圈那么简单。如果行使权利需要仪式感，
    用户就不会行使，而一个没人行使的权利等于不存在。

    重复收回是幂等的空操作：仓储的 `revoked_at IS NULL` 保证第二次点击
    不会把收回时刻改成现在。
    """
    memory = MemoryRepository(conn, campus)
    current = _mine(memory, facet_id, principal_id)
    updated = memory.revoke(facet_id, by=principal_id, now=clock.now()) or current
    return _one(conn, memory, updated, principal_id, repos)


# --- 谁能看到我 ---


@router.get("/me/visibility", response_model=list[VisibilityOut])
def my_visibility(
    conn: ConnDep,
    campus: CampusDep,
    repos: ReposDep,
    principal_id: PrincipalDep,
) -> list[VisibilityOut]:
    """我给出去过、现在还生效的那几次披露。

    过期的和已收回的不在这里——这一屏问的是"现在谁还能看到我"，
    把已经失效的混进来，用户就分不清哪些还需要处理。
    """
    active = repos.envelopes.list_active(principal_id)
    goals = _intent_goals(conn, [e.intent_id for e in active])
    texts = _citable_texts(MemoryRepository(conn, campus), active, principal_id)
    return [
        VisibilityOut(
            envelope_id=envelope.id,
            intent_id=envelope.intent_id,
            for_what=goals.get(envelope.intent_id, ""),
            shows=[
                ShownFieldOut(
                    field_name=grant.field_name,
                    seen_by_others=grant.audience is Audience.CANDIDATES,
                )
                for grant in envelope.grants
            ],
            shows_records=[
                texts[fid] for fid in envelope.cited_facet_ids if fid in texts
            ],
            expires_at=envelope.expires_at,
        )
        for envelope in active
    ]


# --- 内部 ---


def _mine(
    memory: MemoryRepository, facet_id: UUID, principal_id: UUID
) -> MemoryFacet:
    """这条记录必须是我的。

    404 而不是 403：403 等于告诉调用方"这条记录存在，只是不归你"，
    而那本身就是一次泄露。
    """
    facet = memory.get_facet(facet_id)
    if facet is None or facet.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="找不到这条记录")
    return facet


def _companions(
    conn: Connection, event_ids: list[UUID], me: UUID
) -> dict[UUID, list[str]]:
    """每件事上和我一起的人。一次查完，不按事件逐条去查。"""
    if not event_ids:
        return {}
    rows = conn.execute(
        sa.select(event_members.c.event_id, principals.c.display_name)
        .select_from(
            event_members.join(
                principals, principals.c.id == event_members.c.principal_id
            )
        )
        .where(event_members.c.event_id.in_(event_ids))
        .where(event_members.c.principal_id != me)
        .order_by(event_members.c.joined_at.asc(), principals.c.display_name.asc())
    ).all()
    found: dict[UUID, list[str]] = {}
    for row in rows:
        found.setdefault(row.event_id, []).append(row.display_name)
    return found


def _sources(conn: Connection, ids: set[UUID]) -> dict[UUID, RecordSourceOut]:
    if not ids:
        return {}
    rows = conn.execute(
        sa.select(
            evidence.c.id,
            evidence.c.kind,
            evidence.c.title,
            evidence.c.created_at,
        ).where(evidence.c.id.in_(sorted(ids)))
    ).all()
    return {
        row.id: RecordSourceOut(
            evidence_id=row.id,
            kind=row.kind,
            title=row.title,
            added_at=row.created_at,
        )
        for row in rows
    }


def _event_titles(conn: Connection, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = conn.execute(
        sa.select(shared_events.c.id, shared_events.c.title).where(
            shared_events.c.id.in_(sorted(ids))
        )
    ).all()
    return {row.id: row.title for row in rows}


def _intent_goals(conn: Connection, ids: list[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = conn.execute(
        sa.select(intent_signals.c.id, intent_signals.c.goal).where(
            intent_signals.c.id.in_(sorted(set(ids)))
        )
    ).all()
    return {row.id: row.goal for row in rows}


def _citable_texts(
    memory: MemoryRepository,
    active: list[MatchEnvelope],
    principal_id: UUID,
) -> dict[UUID, str]:
    """这几次披露里，**现在真的说得出口**的那些原话。

    走 `citable()` 而不是按 id 直接查 `memory_facets`：后者会把已经收回的
    那条也拿出来，于是界面会告诉用户"这条还在被看"，而事实上它已经不在了。
    收回即时生效，靠的就是这里没有第二条取值路径。
    """
    permitted = {fid for envelope in active for fid in envelope.cited_facet_ids}
    if not permitted:
        return {}
    cited = memory.citable([principal_id], permitted=frozenset(permitted))
    return {c.facet_id: c.text for c in cited}


def _in_use(
    memory: MemoryRepository, principal_id: UUID, repos: ReposDep
) -> dict[UUID, int]:
    """每条记录现在被几处用着。收回过的一律是 0。"""
    active = repos.envelopes.list_active(principal_id)
    counted = Counter(fid for envelope in active for fid in envelope.cited_facet_ids)
    if not counted:
        return {}
    still = _citable_texts(memory, active, principal_id)
    return {fid: n for fid, n in counted.items() if fid in still}


def _cards(
    conn: Connection,
    memory: MemoryRepository,
    facets: list[MemoryFacet],
    principal_id: UUID,
    repos: ReposDep,
) -> list[MyRecordOut]:
    """一批切面转成卡片。来源与事件标题各查一次，不按条去查。"""
    sources = _sources(conn, {e for f in facets for e in f.evidence_ids})
    titles = _event_titles(conn, {f.event_id for f in facets if f.event_id})
    used = _in_use(memory, principal_id, repos)
    return [
        MyRecordOut(
            id=facet.id,
            text=facet.text,
            state=facet.state.value,
            drafted_by_agent=facet.drafted_by_agent,
            created_at=facet.created_at,
            confirmed_at=facet.confirmed_at,
            revoked_at=facet.revoked_at,
            event_id=facet.event_id,
            event_title=titles.get(facet.event_id) if facet.event_id else None,
            # 来源材料被清掉之后这条记录仍然返回，只是指不回去了——
            # 整条 500 或者干脆不返回，用户就连"收回它"都做不到。
            sources=[sources[e] for e in facet.evidence_ids if e in sources],
            in_use=used.get(facet.id, 0),
        )
        for facet in facets
    ]


def _one(
    conn: Connection,
    memory: MemoryRepository,
    facet: MemoryFacet,
    principal_id: UUID,
    repos: ReposDep,
) -> MyRecordOut:
    return _cards(conn, memory, [facet], principal_id, repos)[0]
