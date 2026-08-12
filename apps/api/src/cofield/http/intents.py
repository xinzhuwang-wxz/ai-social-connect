"""意图相关的端点。

一条产品规则贯穿全部：**抽取只产出草稿**。`/intents:compile` 不写库、
不产生任何可被撮合的东西；只有用户校对并 `confirm` 之后，意图才进池子。
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    Reach,
    TeamSize,
    TimeWindow,
)
from cofield.domain.model.skills import normalise
from cofield.domain.ports.intent_extractor import ExtractionFailed
from cofield.http.deps import (
    ClockDep,
    ExtractorDep,
    KindsDep,
    PrincipalDep,
    ReposDep,
)
from cofield.http.schemas import (
    ActionKindOut,
    CompileRequest,
    CompileResponse,
    CreateIntentRequest,
    IntentContentIn,
    IntentOut,
    ReviseIntentRequest,
)

router = APIRouter(tags=["intents"])

#: 低于这个置信度就退回手填表单，而不是拿一份瞎猜的结构去配队。
CONFIDENCE_FLOOR = 0.5
#: 意图的默认存活时长。仍然会被用户自己的截止期截短。
DEFAULT_TTL = timedelta(days=7)


def _to_domain(payload: IntentContentIn) -> IntentContent:
    return IntentContent(
        goal=payload.goal,
        offers=tuple(payload.offers),
        needs=tuple(payload.needs),
        time_window=(
            TimeWindow(
                earliest=payload.time_window.earliest,
                deadline=payload.time_window.deadline,
            )
            if payload.time_window
            else None
        ),
        location_scope=payload.location_scope,
        team_size=(
            TeamSize(
                minimum=payload.team_size.minimum, maximum=payload.team_size.maximum
            )
            if payload.team_size
            else None
        ),
        boundaries=tuple(payload.boundaries),
        open_questions=tuple(payload.open_questions),
    )


@router.get("/action-kinds", response_model=list[ActionKindOut])
def list_action_kinds(kinds: KindsDep) -> list[ActionKindOut]:
    """首屏的场景引子来源。

    新增一个行动类别时首屏自动多一张卡，前端不改代码——这是扩展点的
    可见证据。
    """
    return [ActionKindOut.of(k) for k in kinds.all()]


@router.post("/intents:compile", response_model=CompileResponse)
def compile_intent(
    payload: CompileRequest, extractor: ExtractorDep, clock: ClockDep
) -> CompileResponse:
    """把一句话整理成可检查的结构。**不写库。**"""
    now = clock.now()
    try:
        extraction = extractor.extract(payload.expression, now=now)
    except ExtractionFailed as exc:
        # 抽取失败不能让用户卡住——退回手填表单，原话保留。
        raise HTTPException(
            status_code=422,
            detail={"message": "没能读懂这句话，请手动填写", "reason": str(exc)},
        ) from exc

    return CompileResponse.of(
        extraction,
        extraction.content.conflicts(now=now),
        threshold=CONFIDENCE_FLOOR,
    )


@router.post("/intents", response_model=IntentOut, status_code=201)
def create_intent(
    payload: CreateIntentRequest,
    repos: ReposDep,
    clock: ClockDep,
    principal_id: PrincipalDep,
) -> IntentOut:
    """保存用户校对后的意图。

    `stash=true` 存成念头：只对本人可见、不参与撮合、无过期压力。
    否则存成草稿，等用户确认。两者都还不能被撮合到。
    """
    signal = IntentSignal(
        id=uuid4(),
        principal_id=principal_id,
        state=IntentState.STASHED if payload.stash else IntentState.DRAFT,
        raw_expression=payload.expression,
        content=_to_domain(payload.content),
        created_at=clock.now(),
        action_kind=payload.action_kind,
        # 认不出来的范围一律按全校：**冷启动时缩小范围等于没有匹配**，
        # 而一个打错字的参数不该让他的需求悄悄没人看见。
        reach=Reach(payload.reach) if payload.reach in set(Reach) else Reach.CAMPUS,
    )
    repos.intents.save(signal)
    return IntentOut.of(signal)


@router.get("/intents/{intent_id}", response_model=IntentOut)
def get_intent(intent_id: UUID, repos: ReposDep) -> IntentOut:
    signal = repos.intents.get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    return IntentOut.of(signal)


@router.patch("/intents/{intent_id}", response_model=IntentOut)
def revise_intent(
    intent_id: UUID,
    payload: ReviseIntentRequest,
    repos: ReposDep,
) -> IntentOut:
    """改内容。改完回到草稿——旧的确认不能沿用到新内容上。"""
    signal = repos.intents.get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    try:
        revised = signal.revise(_to_domain(payload.content))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    repos.intents.save(revised)
    return IntentOut.of(revised)


@router.post("/intents/{intent_id}:confirm", response_model=IntentOut)
def confirm_intent(intent_id: UUID, repos: ReposDep, clock: ClockDep) -> IntentOut:
    """用户确认结构化结果无误。这是"未经确认不得进入撮合"的那道门。"""
    signal = repos.intents.get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    try:
        confirmed = signal.confirm(now=clock.now(), ttl=DEFAULT_TTL)
    except ValueError as exc:
        # 冲突要说清是哪几条打架，不能只回一句"参数错误"。
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "conflicts": [
                    {"field": c.field, "detail": c.detail}
                    for c in signal.content.conflicts(now=clock.now())
                ],
            },
        ) from exc
    repos.intents.save(confirmed)

    # **他刚在一件具体的事情里说了自己能出什么。** 记下来，他就能被别人找到。
    #
    # 少了这一步，产品的前提是"你得先跟软件交代自己"：只有去那一屏打过勾的
    # 人才可能出现在任何人的候选里。而人真正说清自己的时刻不在表单里，
    # 在这里——「我能出写脚本」是他为了这件事本来就要写的一句话，
    # 有具体语境，比对着技能表打勾可靠。
    #
    # 归一到词表，词表外的照旧留给原话那一路（`raw_expression` 进语义索引）。
    repos.principals.learned(
        confirmed.principal_id,
        [
            matched
            for offer in confirmed.content.offers
            if (matched := normalise(offer)) is not None
        ],
    )
    return IntentOut.of(confirmed)


@router.post("/intents/{intent_id}:withdraw", response_model=IntentOut)
def withdraw_intent(intent_id: UUID, repos: ReposDep) -> IntentOut:
    signal = repos.intents.get(intent_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="找不到这条需求")
    withdrawn = signal.withdraw()
    repos.intents.save(withdrawn)
    return IntentOut.of(withdrawn)


@router.get("/me/intents", response_model=list[IntentOut])
def list_my_intents(repos: ReposDep, principal_id: PrincipalDep) -> list[IntentOut]:
    """本人的全部意图，含念头。

    念头只出现在这里——系统里没有任何端点会返回**别人的**念头。
    """
    signals = repos.intents.list_for_principal(principal_id)
    return [IntentOut.of(s) for s in signals]
