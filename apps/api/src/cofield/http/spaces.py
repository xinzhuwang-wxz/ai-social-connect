"""共域的端点：一屏、条目、决策门、助手。

四条判断决定了这一层的形状：

1. **身份只从请求头来。** 请求体里出现 `principal_id`、`created_by` 一律无效——
   身份可以由请求体决定的话，任何人都能冒充任何人。这不是失误，是一个
   默认开放的洞。
2. **关掉助手不是故障。** 建议端点在助手关着时返回空列表，不报错——
   报错会让界面弹一个红框，把一个正常选择显示成一次事故。
3. **看不见的空间一律 404。** 不是 403：403 等于确认了这个 id 存在。
4. **助手没有可登录的身份。** 它的 id 由空间派生（`field_agent`），
   也就是知道 space_id 的人都能算出来。所以这一层显式拒绝拿它当人用——
   否则"要真人点头的事助手关不掉"在 HTTP 面上就只剩"它没办法发请求"这一句自觉。

用户看得见的那几段文字（`title`、`label`、`notice`、`summary`）用的是用户词，
领域词只出现在字段名上（07 §2 与 08 §1③）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import Connection

from cofield.adapters.llm import Cassette, LiteLLMComposer
from cofield.adapters.persistence.messages import Kind as MessageKind
from cofield.adapters.persistence.messages import Message, MessageRepository
from cofield.adapters.persistence.repositories import Repositories
from cofield.adapters.persistence.spaces import Item, Space, SpaceRepository
from cofield.domain.ports.composer import Composer, DraftKind
from cofield.http.deps import (
    CampusDep,
    ClockDep,
    ConnDep,
    PrincipalDep,
    ReposDep,
)
from cofield.space import (
    CONFIRMED_BY,
    DECIDERS,
    REACH,
    SOURCE,
    AgentCannotDecide,
    AgentIsOff,
    Canvas,
    CanvasRefused,
    Card,
    DraftDoesNotCount,
    IllegalMove,
    ItemKind,
    ItemKindRegistry,
    MissingProvenance,
    NotYoursToDecide,
    Reach,
    UnknownItemKind,
    field_agent,
    item_kinds,
    person,
)
from cofield.space.agent import CapabilityRefused, FieldAgent, Power, Suggestion

router = APIRouter(tags=["spaces"])

#: 助手在这一层要的两项能力：读已批准的、写草稿。
#:
#: 逐次现发而不是长期持有——令牌活不过一个请求，所以"成员一变旧令牌作废"
#: 这条在 HTTP 面上是自动成立的。
_SUGGESTION_POWERS = frozenset({Power.READ_APPROVED, Power.DRAFT})

#: 起草下一步用哪一档。
#:
#: `DraftKind` 里没有"共域下一步建议"这一档，四档里 `PROOF_NARRATION`
#: 是唯一"把已有条件转写成一句话"的用途，语义最近，而且它是四档里
#: 降级最不痛的一档。新增一档要动领域端口，不归这一层——记在交接里。
_SUGGESTION_PURPOSE = DraftKind.PROOF_NARRATION


# --- 装配 -------------------------------------------------------------------


def get_item_kinds() -> ItemKindRegistry:
    """随产品发布的条目类型。

    和行动类别注册表同一个思路：新增一种条目是新增一条声明，
    界面上多一个可选项，前端不改代码。
    """
    return item_kinds


def get_composer(request: Request) -> Composer:
    """起草者从应用状态取，取不到就用磁带包着的真实现。

    默认包磁带（默认 replay）是刻意的：**没配就一次真调用都不会发生**，
    而不是"忘了配就开始花钱"。线上把 `COFIELD_LLM_MODE` 设成 `off` 直通。
    """
    composer: Composer | None = getattr(request.app.state, "composer", None)
    return composer or Cassette(LiteLLMComposer())


ItemKindsDep = Annotated[ItemKindRegistry, Depends(get_item_kinds)]
ComposerDep = Annotated[Composer, Depends(get_composer)]


@dataclass(frozen=True, slots=True)
class Board:
    """一个空间的读写面：连接、空间本身、画布、当前是谁在动手。

    做成依赖而不是让每个端点自己拼，是因为这里挂着两道必须**每次**都过的
    检查——看不见的空间 404、助手的身份不能当人用。靠每个端点自己记得，
    总会有一个忘掉，而忘掉的那一个就是洞。
    """

    conn: Connection
    campus: str
    repo: SpaceRepository
    space: Space
    canvas: Canvas
    kinds: ItemKindRegistry
    #: 当前用户。来自请求头，**永远不来自请求体**。
    me: UUID


def get_board(
    space_id: UUID,
    conn: ConnDep,
    campus: CampusDep,
    principal_id: PrincipalDep,
    kinds: ItemKindsDep,
) -> Board:
    repo = SpaceRepository(conn, campus)
    space = repo.get(space_id)
    if space is None:
        # 别的租户的空间在这里表现为"不存在"——连接已绑定租户，行级安全
        # 直接把它过滤掉了。回 404 而不是 403：403 等于确认了这个 id 存在。
        raise HTTPException(status_code=404, detail="找不到这个空间")
    if principal_id == field_agent(space_id).id:
        # 助手的 id 由 space_id 派生，谁都算得出来。不挡住的话，
        # 把它写进「谁必须点头」就等于给了它一张点头的票。
        raise HTTPException(status_code=403, detail="助手不能当成一个人来用")
    return Board(
        conn=conn,
        campus=campus,
        repo=repo,
        space=space,
        canvas=Canvas(repo, space, kinds),
        kinds=kinds,
        me=principal_id,
    )


BoardDep = Annotated[Board, Depends(get_board)]


# --- 契约 -------------------------------------------------------------------


class ItemKindOut(BaseModel):
    """一种条目的声明。前端据此生成"放一条东西"的选项与表单。"""

    key: str
    #: 界面上管它叫什么。这一列已经是用户词了。
    label: str
    states: list[str]
    done_states: list[str]
    counts_toward_progress: bool
    #: 终态只能由真人逐个点头达成。前端据此把它做成决定卡，不是勾选框。
    needs_human_decision: bool
    #: 缺了就不许放进来的 `extras` 键。
    required_extras: list[str]
    agent_may_draft: bool

    @classmethod
    def of(cls, kind: ItemKind) -> ItemKindOut:
        return cls(
            key=kind.key,
            label=kind.label,
            states=list(kind.states),
            done_states=sorted(kind.done_states),
            counts_toward_progress=kind.counts_toward_progress,
            needs_human_decision=kind.needs_human_decision,
            required_extras=list(kind.required_extras),
            agent_may_draft=kind.agent_may_draft,
        )


class ItemOut(BaseModel):
    """画布上的一条东西。

    `extras` 不原样透出：它在库里是开放的 JSON，透出去前端拿到的就是一个
    `additionalProperties: true`，也就是回到手写类型。四个有约定含义的键在
    这里显式成型；将来某种条目带了新键，这里补一行——契约本来就该是显式的。
    """

    id: UUID
    space_id: UUID
    kind: str
    #: 界面上管这一类叫什么。
    label: str
    title: str
    body: str | None = None
    state: str
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    #: 助手写的。前端据此给 AI 草稿一条独立视觉通道（08 §2.1），
    #: 和真人确认过的内容一眼可辨。
    drafted_by_agent: bool
    accepted_by: UUID | None = None
    #: 助手写的且还没有真人认领。这条不算数：不计完成度、不落任何人待办、
    #: 做不了任何结论。
    awaiting_a_person: bool
    #: 这件事必须由谁点头，以及谁已经点了。
    deciders: list[UUID] = []
    confirmed_by: list[UUID] = []
    #: 这样东西谁能看见。只有声明了可见范围的类型才有。
    reach: Reach | None = None
    source: str | None = None
    #: 这一刻这张卡该说的那句话。没什么要说的时候是 null——
    #: 每张卡都挂一句话等于每张卡都没话说。
    notice: str | None = None

    @classmethod
    def of(cls, item: Item, *, label: str, notice: str | None = None) -> ItemOut:
        raw_reach = item.extras.get(REACH)
        raw_source = item.extras.get(SOURCE)
        return cls(
            id=item.id,
            space_id=item.space_id,
            kind=item.kind,
            label=label,
            title=item.title,
            body=item.body,
            state=item.state,
            assignee_id=item.assignee_id,
            due_at=item.due_at,
            created_by=item.created_by,
            created_at=item.created_at,
            updated_at=item.updated_at,
            drafted_by_agent=item.drafted_by_agent,
            accepted_by=item.accepted_by,
            awaiting_a_person=item.awaiting_a_person,
            deciders=_people(item, DECIDERS),
            confirmed_by=_people(item, CONFIRMED_BY),
            reach=Reach(raw_reach) if raw_reach else None,
            source=str(raw_source) if raw_source else None,
            notice=notice,
        )


class ProgressOut(BaseModel):
    """做完了多少。**件数，不是百分比**——这个产品不做总分（07 §6）。"""

    done: int
    total: int


class SpaceOut(BaseModel):
    """一屏。

    四个分组对着验收标准的四句话：要做什么（`cards`）、谁负责什么（卡片上的
    负责人）、卡在哪（`stuck`）、还有哪些决定没关（`open_gates`）。
    `drafts` 是第五样——助手写了、等真人过目的，它单独一栏，因为它还不算数。

    `open_gates` 与 `stuck` 是 `cards` 的子集，不是另一批东西。照搬领域视图
    的分组，不做层间语义翻译。
    """

    id: UUID
    #: 界面上这个空间就叫项目自己的名字（07 §5）。
    title: str
    #: 助手开着没有。关着的时候界面把那张卡显示成不可用，其余全部照常（08 §3.7）。
    agent_enabled: bool
    cards: list[ItemOut]
    open_gates: list[ItemOut]
    stuck: list[ItemOut]
    drafts: list[ItemOut]
    progress: ProgressOut
    #: 一句话概括这一屏。空空的空间说"还没有要做的事"，不是一片空白。
    summary: str


class AddItemRequest(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    #: 派给谁。**这不是身份**——把活派给别人是正常操作，冒充别人不是。
    assignee_id: UUID | None = None
    #: 必须带时区。领域里拿它和注入的时钟比大小，少了时区那次比较会炸——
    #: 在边界上拒掉，比在画布里炸成 500 好。
    due_at: AwareDatetime | None = None
    #: 这一类自己声明的必填项：「要定的事」要写明谁必须点头，
    #: 「我们做的东西」要写明来源与谁能看见。缺了在这一层就被拒。
    extras: dict[str, Any] = {}


class ReviseItemRequest(BaseModel):
    """推进、指派、改可见范围。

    三样都可选，且"没给"与"给了 null"是两件事：`assignee_id: null` 是
    把活放回去，不给这个字段才是不动它。区分靠 `model_fields_set`。
    """

    state: str | None = None
    assignee_id: UUID | None = None
    reach: Reach | None = None


class ToggleAgentRequest(BaseModel):
    enabled: bool


class SuggestionOut(BaseModel):
    """一条建议。

    每条都是独立的一条，不是一段话里的一句——混在一段话里，用户要么
    全接受要么全拒绝，"每条都带一个「不用了」"就无从谈起（07 原则四）。
    """

    kind: str
    title: str
    #: 它是根据空间里的什么写的。看不到依据的建议，"人类决定"就只是点一下按钮。
    grounded_in: list[str]


class AcceptSuggestionRequest(BaseModel):
    """采纳一条建议。

    带回 `grounded_in` 是因为建议本身不落库——助手每刷新一次屏幕就往画布上
    写一条，那一栏很快就成了垃圾堆。代价是这段文字由客户端带回来，
    但**谁采纳的**记在 `accepted_by` 上，责任仍然落在按下按钮的那个人身上。
    """

    kind: str
    title: str = Field(min_length=1, max_length=200)
    grounded_in: list[str] = []


# --- 拒绝怎么翻译成状态码 ---------------------------------------------------

#: 领域拒绝 → HTTP 状态码。分三档，界线是"谁做错了什么"：
#: 403 是这个人没有这个权（换个人可能就行），409 是这一步现在走不通
#: （换个时机、或者先做别的），422 是这次请求本身不成立。
#: 全塞成 400 的话，前端只能靠读中文提示来决定要不要重试。
_REFUSAL_STATUS: tuple[tuple[type[CanvasRefused], int], ...] = (
    (UnknownItemKind, 422),
    (MissingProvenance, 422),
    (CapabilityRefused, 403),
    (AgentCannotDecide, 403),
    (NotYoursToDecide, 403),
    (AgentIsOff, 409),
    (DraftDoesNotCount, 409),
    (IllegalMove, 409),
)


def _refused(exc: CanvasRefused) -> HTTPException:
    for kind, status in _REFUSAL_STATUS:
        if isinstance(exc, kind):
            return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


# --- 内部 -------------------------------------------------------------------


def _people(item: Item, key: str) -> list[UUID]:
    raw: Any = item.extras.get(key) or []
    return [u if isinstance(u, UUID) else UUID(str(u)) for u in raw]


def _find(board: Board, item_id: UUID) -> Item:
    """按 id 取一条，取不到就 404。

    画布把"这个空间里没有它"抛成一次非法操作，而 HTTP 面上这是两件事：
    找不到该 404，走不通才是 409。不在这里分开，前端会把一次打错的 id
    当成一次状态冲突去重试。
    """
    item = board.repo.get_item(item_id)
    if item is None or item.space_id != board.space.id:
        raise HTTPException(status_code=404, detail="这个空间里没有这条东西")
    return item


def _label(board: Board, item: Item) -> str:
    return board.kinds.get(item.kind).label


def _names(repos: Repositories, items: Sequence[Item]) -> dict[UUID, str]:
    """把「还差 2 个人点头」变成「还差陈牧和苏晚点头」。

    多出来的不是礼貌，是可行动性——看到名字的人知道该去戳谁（07 §6）。
    查不到名字的就不放进来，画布会自己退回人数，不编一个名字出来。
    """
    wanted: set[UUID] = set()
    for item in items:
        wanted.update(_people(item, DECIDERS))
    found: dict[UUID, str] = {}
    for principal_id in wanted:
        principal = repos.principals.get(principal_id)
        if principal is not None:
            found[principal_id] = principal.display_name
    return found


def _cards(group: Sequence[Card]) -> list[ItemOut]:
    return [ItemOut.of(c.item, label=c.label, notice=c.notice) for c in group]


def _screen(board: Board, repos: Repositories, *, now: datetime) -> SpaceOut:
    view = board.canvas.view(
        now=now, names=_names(repos, board.repo.list_items(board.space.id))
    )
    return SpaceOut(
        id=board.space.id,
        title=view.title,
        agent_enabled=board.space.agent_enabled,
        cards=_cards(view.cards),
        open_gates=_cards(view.open_gates),
        stuck=_cards(view.stuck),
        drafts=_cards(view.drafts),
        progress=ProgressOut(done=view.progress.done, total=view.progress.total),
        summary=view.summary,
    )


def _agent(board: Board, composer: Composer) -> FieldAgent:
    return FieldAgent(
        board.conn, board.canvas, composer=composer, campus_id=board.campus
    )


# --- 端点 -------------------------------------------------------------------


@router.get("/item-kinds", response_model=list[ItemKindOut])
def list_item_kinds(kinds: ItemKindsDep) -> list[ItemKindOut]:
    """能往空间里放哪几类东西。

    新增一种条目时这里自动多一项，前端不改代码——和首屏的场景引子
    是同一个扩展点思路。
    """
    return [ItemKindOut.of(k) for k in kinds.all()]


@router.get("/spaces/{space_id}", response_model=SpaceOut)
def get_space(board: BoardDep, repos: ReposDep, clock: ClockDep) -> SpaceOut:
    """共域一屏。

    新空间返回的是一个可用的空态——`summary` 说"还没有要做的事"，
    不是错误也不是一片空白。一屏能看见的四件事都在分组里。
    """
    return _screen(board, repos, now=clock.now())


@router.post("/spaces/{space_id}/items", response_model=ItemOut, status_code=201)
def add_item(
    payload: AddItemRequest, board: BoardDep, clock: ClockDep
) -> ItemOut:
    """往画布上放一条东西。

    放的人是请求头里的那个人。请求体里写谁都不算——`created_by` 由这一层
    填，不接受任何外部输入。
    """
    try:
        item = board.canvas.add(
            payload.kind,
            payload.title,
            by=person(board.me),
            now=clock.now(),
            body=payload.body,
            assignee_id=payload.assignee_id,
            due_at=payload.due_at,
            extras=payload.extras,
        )
    except UnknownItemKind as exc:
        # 领域里那句话带着注册表的内部清单，那是给工程师看的。
        # 界面上只说这一件事：没有这一类。可选项来自 `GET /item-kinds`。
        raise HTTPException(status_code=422, detail="没有这一类东西") from exc
    except CanvasRefused as exc:
        raise _refused(exc) from exc
    except ValueError as exc:
        # `extras` 是开放字段，里面的枚举值（比如谁能看见）由领域校验。
        # 校验不过是这次请求不成立，不是服务出错——落成 500 会被当成故障去重试。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ItemOut.of(item, label=_label(board, item))


@router.patch("/spaces/{space_id}/items/{item_id}", response_model=ItemOut)
def revise_item(
    item_id: UUID,
    payload: ReviseItemRequest,
    board: BoardDep,
    clock: ClockDep,
) -> ItemOut:
    """推进一步、换个负责人，或者改谁能看见。

    要真人点头的那一类走不到终态：那条路只有 `:confirm`。留一条 `advance`
    的后门，"助手关不掉决策门"就白写了——而后门在 HTTP 上比在库里更好找。
    """
    item = _find(board, item_id)
    now = clock.now()
    by = person(board.me)
    try:
        if "assignee_id" in payload.model_fields_set:
            item = board.canvas.assign(item_id, to=payload.assignee_id, by=by, now=now)
        if payload.state is not None:
            item = board.canvas.advance(item_id, to=payload.state, by=by, now=now)
        if payload.reach is not None:
            item = board.canvas.change_reach(item_id, to=payload.reach, by=by, now=now)
    except CanvasRefused as exc:
        raise _refused(exc) from exc
    return ItemOut.of(item, label=_label(board, item))


@router.post("/spaces/{space_id}/items/{item_id}:confirm", response_model=ItemOut)
def confirm_item(item_id: UUID, board: BoardDep, clock: ClockDep) -> ItemOut:
    """点头。

    点头的是请求头里的那个人，这个端点**没有请求体**——身份可以由请求体
    决定的话，"谁点的头"就成了一句可以随便填的话。

    全体点齐才算关上。少一个人就关上等于"没读的人默认被代表"，
    那正是群聊做错的事。
    """
    _find(board, item_id)
    try:
        item = board.canvas.confirm(item_id, by=person(board.me), now=clock.now())
    except CanvasRefused as exc:
        raise _refused(exc) from exc
    return ItemOut.of(item, label=_label(board, item))


@router.post("/spaces/{space_id}/agent:toggle", response_model=SpaceOut)
def toggle_agent(
    payload: ToggleAgentRequest,
    board: BoardDep,
    repos: ReposDep,
    clock: ClockDep,
) -> SpaceOut:
    """开关助手。

    关掉之后返回的仍然是完整的一屏——这正是要给前端看的：**人工那几栏
    一条都没少**，只是"等你过目"那一栏空了。草稿的行还留在库里，
    重新打开它们原样回来。

    这里不动策略纪元：令牌活不过一个请求，没有需要作废的旧令牌。
    """
    board.repo.set_agent_enabled(board.space.id, enabled=payload.enabled)
    space = board.repo.get(board.space.id)
    if space is None:  # pragma: no cover —— 同一个事务里刚读到过
        raise HTTPException(status_code=404, detail="找不到这个空间")
    switched = Board(
        conn=board.conn,
        campus=board.campus,
        repo=board.repo,
        space=space,
        canvas=Canvas(board.repo, space, board.kinds),
        kinds=board.kinds,
        me=board.me,
    )
    return _screen(switched, repos, now=clock.now())


@router.get("/spaces/{space_id}/suggestions", response_model=list[SuggestionOut])
def list_suggestions(
    board: BoardDep, composer: ComposerDep, clock: ClockDep
) -> list[SuggestionOut]:
    """助手看了一眼空间，给几条下一步。

    **助手关着的时候返回空列表，HTTP 200。** 关掉助手是一个正常状态不是
    一次故障——回 4xx 会让界面弹一个红框，等于把用户自己的选择显示成
    出了问题。模型说不出话（服务挂了、磁带没命中）也一样：闭嘴，不报错。

    建议不落库。刷一次屏就往画布上写一条，那一栏很快就成了垃圾堆——
    真人按下"采纳"它才进画布。
    """
    if not board.space.agent_enabled:
        return []
    agent = _agent(board, composer)
    try:
        token = agent.issue(
            purpose=_SUGGESTION_PURPOSE, powers=_SUGGESTION_POWERS, now=clock.now()
        )
        drafted = agent.suggest_next_steps(token, now=clock.now())
    except CanvasRefused as exc:
        raise _refused(exc) from exc
    return [
        SuggestionOut(
            kind=s.kind, title=s.title, grounded_in=list(s.grounded_in)
        )
        for s in drafted
    ]


@router.post(
    "/spaces/{space_id}/suggestions:accept", response_model=ItemOut, status_code=201
)
def accept_suggestion(
    payload: AcceptSuggestionRequest,
    board: BoardDep,
    composer: ComposerDep,
    clock: ClockDep,
) -> ItemOut:
    """采纳一条建议：把它放进画布，并记下是谁认的。

    逐条采纳，没有一键全收——一键全收和让助手自己写进去没有区别，
    中间那个人只是按了一下。落进来的条目**两个署名都留着**：
    `drafted_by_agent` 记它是助手写的，`accepted_by` 记是谁认的。
    """
    now = clock.now()
    agent = _agent(board, composer)
    try:
        token = agent.issue(
            purpose=_SUGGESTION_PURPOSE, powers=_SUGGESTION_POWERS, now=now
        )
        placed = agent.put_on_canvas(
            token,
            Suggestion(
                kind=payload.kind,
                title=payload.title,
                grounded_in=tuple(payload.grounded_in),
            ),
            now=now,
        )
        # 刚写进画布的条目一定带 id；断言在这里是给类型检查一个依据。
        assert placed.item_id is not None
        item = board.canvas.accept(placed.item_id, by=person(board.me), now=now)
    except UnknownItemKind as exc:
        raise HTTPException(status_code=422, detail="没有这一类东西") from exc
    except CanvasRefused as exc:
        raise _refused(exc) from exc
    return ItemOut.of(item, label=_label(board, item))


# --- 群聊（N+1）-------------------------------------------------------------


class MessageOut(BaseModel):
    id: UUID
    author_id: UUID
    #: 是不是助手说的。**一眼可辨**——界面靠它把助手的话和人的话分开，
    #: 分不清谁说的，"AI 起草、人类决定"就只是一句话。
    is_agent: bool
    kind: str
    text: str
    created_at: datetime
    replies_to: UUID | None = None
    #: 这张话题卡关于哪件还没定的事。
    about_item_id: UUID | None = None


class ThreadOut(BaseModel):
    topic: MessageOut
    replies: list[MessageOut]
    #: 有没有人回过。**没人回不是失败，是信号**——它说明这张卡问得不对，
    #: 或者这件事大家其实不在意。
    answered: bool


class ChatOut(BaseModel):
    """整条聊天记录 + 话题卡。

    **不分页。**「大家能看到整体的聊天记录」是这一层的承诺；一个默认只给
    最近五十条的接口，会让"看看当时怎么说的"变成一件做不到的事。
    """

    messages: list[MessageOut]
    threads: list[ThreadOut]


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    #: 回在哪张话题卡下面。空 = 说在主线上。
    replies_to: UUID | None = None


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        author_id=message.author_id,
        is_agent=message.is_agent,
        kind=message.kind.value,
        text=message.text,
        created_at=message.created_at,
        replies_to=message.replies_to,
        about_item_id=message.about_item_id,
    )


@router.get("/spaces/{space_id}/chat", response_model=ChatOut)
def read_chat(board: BoardDep) -> ChatOut:
    """说过的话，全部。"""
    repo = MessageRepository(board.conn, board.campus)
    return ChatOut(
        messages=[_message_out(m) for m in repo.history(board.space.id)],
        threads=[
            ThreadOut(
                topic=_message_out(t.topic),
                replies=[_message_out(r) for r in t.replies],
                answered=t.answered,
            )
            for t in repo.threads(board.space.id)
        ],
    )


@router.post("/spaces/{space_id}/chat", response_model=MessageOut, status_code=201)
def say(board: BoardDep, payload: SayRequest, clock: ClockDep) -> MessageOut:
    """说一句话。

    **作者来自请求头，不来自请求体**——否则任何人都能以任何人的名义发言，
    而聊天记录是这个组以后唯一能回去查的东西。
    """
    repo = MessageRepository(board.conn, board.campus)
    try:
        message = repo.say(
            board.space.id,
            author_id=board.me,
            text=payload.text,
            now=clock.now(),
            replies_to=payload.replies_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _message_out(message)


@router.post("/spaces/{space_id}/chat:topics", response_model=list[MessageOut])
def raise_topics(
    board: BoardDep, composer: ComposerDep, clock: ClockDep
) -> list[MessageOut]:
    """让助手把还没定的事，变成几句可以回答的话。

    **它挑不了话题，只能把已经存在的待定事项写得好回答一点。** 输入是
    开着的决策门和成局证明里留给真人的那几条；凭空造话题的助手会很快
    被所有人忽略，而一旦被忽略，之后它说什么都没人看了。

    助手关着时返回空数组 + 200：关掉助手是正常状态不是故障。
    同一件事不问第二遍——问第二遍说明它没在听。
    """
    now = clock.now()
    if not board.space.agent_enabled:
        return []

    agent = _agent(board, composer)
    repo = MessageRepository(board.conn, board.campus)
    view = board.canvas.view(now=now)
    unsettled = [(card.item.id, card.item.title) for card in view.open_gates]

    try:
        token = agent.issue(
            purpose=DraftKind.OPEN_QUESTION,
            powers=frozenset({Power.ASK}),
            now=now,
        )
        topics = agent.open_questions(
            token,
            unsettled=unsettled,
            already_asked=repo.already_asked_about(board.space.id),
            now=now,
        )
    except CanvasRefused:
        return []

    said = [
        repo.say(
            board.space.id,
            author_id=field_agent(board.space.id).id,
            text=topic.text,
            now=now,
            kind=MessageKind.TOPIC,
            is_agent=True,
            about_item_id=topic.about_item_id,
        )
        for topic in topics
    ]
    return [_message_out(m) for m in said]
