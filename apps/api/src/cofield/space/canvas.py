"""结构化画布：条目操作与可见性。

这一份文件是"共域不是群聊"这句话的实现。群聊里信息会沉底、决定没有归属、
没读的人默认被代表；画布上每条东西都有类型、状态、负责人和截止时刻，
一屏能看见**要做什么、谁负责什么、卡在哪、还有哪些决定没关**。

四条判断写进了代码结构，不只写在注释里：

1. **助手是一张卡片，不是运行时。** 关掉开关之后所有人工路径一步不少——
   每一处拒绝都发生在"动手的是助手"这个分支里，没有一处发生在人工分支里。
2. **AI 起草，人类决定。** 助手写的条目在被真人逐条采纳之前不算数，
   而"不算数"是可执行的四条行为（见 `_effective` 与 `DraftDoesNotCount`），
   不是一句宣言。
3. **需要真人点头的条目，助手一律关不掉。** 这条不接受配置：声明里能配的是
   "谁必须点头"，不是"要不要真人点头"。把它做成开关，第一个赶进度的人就会关掉它。
4. **这里没有任何一种条目的名字。** 类型全部由注册表声明，
   规则挂在声明的属性上而不是挂在字符串上——新增一种条目应该是新增一条声明。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4, uuid5

from cofield.adapters.persistence.spaces import Item, Space, SpaceRepository

#: 场域智能体身份的命名空间。
#:
#: 助手的 id 由**空间**派生而不是随机生成，也不复用任何成员的 id：
#: 它属于共同事件，不属于任一成员（CONTEXT「场域智能体」）。派生还顺带
#: 挡住了跨共域串联——两个空间的助手拿不到同一个身份，日志里也分得开。
FIELD_AGENT_NAMESPACE = UUID("b0f5d3d1-3e1e-4a4a-9d2e-0f5a1c7b6e42")

#: 被丢弃的条目。横切所有类型，所以不写进任何一条声明的状态表里。
#: 丢弃不是删除——行留着，申诉时要查得到当时都提过什么。
DISCARDED = "discarded"

#: `extras` 里几个有约定含义的键。
DECIDERS = "deciders"
CONFIRMED_BY = "confirmed_by"
ABOUT = "about"
SOURCE = "source"
REACH = "reach"


class Reach(StrEnum):
    """一样东西谁能看见。

    只有两档，且默认是窄的那一档。档位多了就没人认真选，
    而"发出去"这件事不该有一个随手滑过去的中间态。
    """

    #: 只有这个空间里的人。
    OURS = "ours"
    #: 空间之外也能看见。
    OUTSIDE = "outside"


# --- 拒绝 -------------------------------------------------------------------


class CanvasRefused(Exception):
    """一次写入被拒。

    **拒绝一律抛出，不静默忽略。** 静默忽略会让"助手关不掉决策门"这种
    不变量在界面上表现为"点了没反应"，而没反应的按钮迟早会被当成 bug 修掉。
    """


class UnknownItemKind(CanvasRefused):
    """没注册过的条目类型。不静默回退到某个默认值。"""


class AgentIsOff(CanvasRefused):
    """助手被关掉了，它的写入路径整条不通。人工路径不受影响。"""


class AgentCannotDecide(CanvasRefused):
    """助手越过了起草的边界。AI 可以代为表达，但不能代为承诺。"""


class DraftDoesNotCount(CanvasRefused):
    """还没被真人采纳的草稿参与不了任何事。"""


class NotYoursToDecide(CanvasRefused):
    """这个决定不归你点头。"""


class IllegalMove(CanvasRefused):
    """这条声明里没有这一步。"""


class MissingProvenance(CanvasRefused):
    """来源、可见范围或"谁点头"缺了。

    没有来源和可见范围的东西不能成为权威长期记忆（不变量 5），
    所以缺了就不许写进来，而不是先收下再补。
    """


# --- 谁在动手 ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Actor:
    """一次操作背后的那只手。

    是人还是助手必须在**签名里**就分得开。做成运行时判断的话，
    "AI 起草，人类决定"就得靠每个调用点自己记得——记不住的那次就是事故。
    """

    id: UUID
    is_agent: bool = False


def person(principal_id: UUID) -> Actor:
    return Actor(principal_id)


def field_agent(space_id: UUID) -> Actor:
    """这个空间的助手。身份由空间派生，见 `FIELD_AGENT_NAMESPACE`。"""
    return Actor(uuid5(FIELD_AGENT_NAMESPACE, str(space_id)), is_agent=True)


# --- 条目类型注册表 ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ItemKind:
    """一种条目的声明。

    加一种条目 = 加一条声明。规则挂在这些属性上，不挂在 `key` 上——
    挂在 key 上就等于在画布里写死了一张类型清单，那个扩展点就是假的。
    """

    key: str
    #: 界面上管它叫什么。这里出现的是用户词，不是领域词（07 §2）。
    label: str
    #: 生命周期。第一个是初始状态。
    states: tuple[str, ...]
    #: 终态。
    done_states: frozenset[str] = frozenset()
    #: 计不计入"这件事做完了多少"。
    counts_toward_progress: bool = False
    #: 终态只能由真人点头达成。**声明能配的是这个；一旦为真，
    #: 助手永远关不掉它——那一条是规则，不是配置。**
    needs_human_decision: bool = False
    #: 缺了就不许写进来的 `extras` 键。
    required_extras: tuple[str, ...] = ()
    #: 助手能不能起草这一类。
    agent_may_draft: bool = True

    def __post_init__(self) -> None:
        if not self.states:
            raise ValueError(f"{self.key}：至少要有一个状态")
        if not self.done_states <= set(self.states):
            raise ValueError(f"{self.key}：终态不在声明的状态里")
        if self.needs_human_decision and not self.done_states:
            raise ValueError(f"{self.key}：要真人点头却没有终态，那就永远关不掉")

    @property
    def initial(self) -> str:
        return self.states[0]


class ItemKindRegistry:
    """按 key 查类型。找不到时明确报错——静默回退会让"忘了注册"藏到线上。"""

    def __init__(self, kinds: Sequence[ItemKind]) -> None:
        keys = [k.key for k in kinds]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"条目类型 key 重复：{duplicates}")
        self._by_key = {k.key: k for k in kinds}

    def __len__(self) -> int:
        return len(self._by_key)

    def all(self) -> tuple[ItemKind, ...]:
        return tuple(self._by_key.values())

    def get(self, key: str) -> ItemKind:
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownItemKind(
                f"没注册过的条目类型：{key}。已注册：{sorted(self._by_key)}"
            ) from None


# --- 一屏看见什么 -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Progress:
    """做完了多少。

    分母只数**算数的**条目：助手起草而没人认领的东西既不进分子也不进分母。
    只挡分子的话，助手多写几条就能把进度冲淡——那等于让它替全组下结论。
    """

    done: int
    total: int


@dataclass(frozen=True, slots=True)
class Card:
    """画布上的一张卡片：一条条目，加上它这一刻该说的那句话。"""

    item: Item
    label: str
    notice: str | None


@dataclass(frozen=True, slots=True)
class CanvasView:
    """一屏。

    四个分组对着验收标准的四句话：要做什么（`cards`）、谁负责什么
    （卡片上的负责人）、卡在哪（`stuck`）、还有哪些决定没关（`open_gates`）。
    `drafts` 是第五样东西——助手写了、等真人过目的，它单独一栏，
    因为它还不算数。
    """

    title: str
    cards: tuple[Card, ...]
    open_gates: tuple[Card, ...]
    stuck: tuple[Card, ...]
    drafts: tuple[Card, ...]
    progress: Progress
    summary: str


class Canvas:
    """共域的写侧与读侧。

    注册表由外面传进来，没有默认值——默认值会让这份文件重新知道
    "系统里有哪几种条目"，扩展点也就退化成了一句话。
    """

    def __init__(
        self, repo: SpaceRepository, space: Space, kinds: ItemKindRegistry
    ) -> None:
        self._repo = repo
        self._space = space
        self._kinds = kinds

    @property
    def space(self) -> Space:
        return self._space

    # --- 写 ---

    def add(
        self,
        kind_key: str,
        title: str,
        *,
        by: Actor,
        now: datetime,
        body: str | None = None,
        assignee_id: UUID | None = None,
        due_at: datetime | None = None,
        extras: Mapping[str, Any] | None = None,
    ) -> Item:
        """往画布上放一条东西。

        助手放上来的一律带 `drafted_by_agent`，并且 `accepted_by` 为空——
        它进的是"等你过目"那一栏，不进任何人的待办。
        """
        kind = self._kinds.get(kind_key)
        payload: dict[str, Any] = dict(extras or {})

        if by.is_agent:
            self._agent_may_draft(kind)

        missing = [key for key in kind.required_extras if not payload.get(key)]
        if missing:
            raise MissingProvenance(f"{kind.key} 缺了必须写明的：{missing}")
        if kind.needs_human_decision:
            payload[DECIDERS] = [str(u) for u in _uuids(payload, DECIDERS)]
            payload.setdefault(CONFIRMED_BY, [])
        if REACH in kind.required_extras:
            payload[REACH] = Reach(payload[REACH]).value

        item = Item(
            id=uuid4(),
            space_id=self._space.id,
            kind=kind.key,
            title=title,
            state=kind.initial,
            created_by=by.id,
            created_at=now,
            updated_at=now,
            body=body,
            assignee_id=assignee_id,
            due_at=due_at,
            drafted_by_agent=by.is_agent,
            extras=payload,
        )
        self._repo.add_item(item)
        return item

    def accept(self, item_id: UUID, *, by: Actor, now: datetime) -> Item:
        """真人逐条采纳一份草稿。

        逐条而不是一键全收：一键全收和让助手自己写进去没有区别，
        中间那个人只是按了一下。
        """
        item, _ = self._load(item_id)
        self._a_person(by, "采纳")
        self._assistant_channel_open()
        if not item.awaiting_a_person:
            raise IllegalMove("这条不是等着被采纳的草稿")
        return self._save(replace(item, accepted_by=by.id, updated_at=now))

    def discard(self, item_id: UUID, *, by: Actor, now: datetime) -> Item:
        """真人丢掉一份草稿。行留着，只是不再出现在画布上。

        它是 `accept` 的另一半。没有它，"关掉助手不删草稿"就成了
        "那些草稿永远清不掉"。
        """
        item, _ = self._load(item_id)
        self._a_person(by, "丢弃")
        self._assistant_channel_open()
        if not item.awaiting_a_person:
            raise IllegalMove("这条已经是真人的东西了，不能当草稿丢掉")
        return self._save(replace(item, state=DISCARDED, updated_at=now))

    def assign(
        self, item_id: UUID, *, to: UUID | None, by: Actor, now: datetime
    ) -> Item:
        """派活，或者把活放回去。"""
        item, _ = self._load(item_id)
        self._may_change(item, by)
        return self._save(replace(item, assignee_id=to, updated_at=now))

    def advance(self, item_id: UUID, *, to: str, by: Actor, now: datetime) -> Item:
        """推进状态。

        需要真人点头的那一类走不到终态——它们只能靠 `confirm` 关掉，
        而 `confirm` 只认真人。留一条 `advance` 的后门，前面那条不变量就白写了。
        """
        item, kind = self._load(item_id)
        if to not in kind.states:
            raise IllegalMove(f"{kind.key} 没有 {to!r} 这个状态：{kind.states}")
        if kind.needs_human_decision and to in kind.done_states:
            raise NotYoursToDecide("这一类要相关的人逐个点头才算关上")
        self._may_change(item, by)
        return self._save(replace(item, state=to, updated_at=now))

    def confirm(self, item_id: UUID, *, by: Actor, now: datetime) -> Item:
        """点头。

        **助手点不了这个头，这一条是硬的。** 它排在"你是不是该点头的人"
        之前判断，是为了让失败的原因不含糊：助手被拒不是因为它不在名单上，
        是因为它是助手——把它写进名单也一样过不去。

        全体点齐才关上。少一个人就关上等于"没读的人默认被代表"，
        那正是群聊做错的事。重复点头不算两次。
        """
        item, kind = self._load(item_id)
        if not kind.needs_human_decision:
            raise IllegalMove(f"{kind.key} 不是靠点头关上的")
        if by.is_agent:
            raise AgentCannotDecide("要真人点头的事，助手关不掉")
        if item.awaiting_a_person:
            raise DraftDoesNotCount("助手起草的这一条还没人认，它做不了结论")
        if item.state in kind.done_states:
            raise IllegalMove("这件事已经定了")

        deciders = _uuids(item.extras, DECIDERS)
        if by.id not in deciders:
            raise NotYoursToDecide("这个决定不归你点头")

        confirmed = {*_uuids(item.extras, CONFIRMED_BY), by.id}
        extras = dict(item.extras)
        extras[CONFIRMED_BY] = [str(u) for u in confirmed]
        state = item.state
        if set(deciders) <= confirmed:
            state = sorted(kind.done_states)[0]
        return self._save(replace(item, state=state, extras=extras, updated_at=now))

    def change_reach(
        self, item_id: UUID, *, to: Reach, by: Actor, now: datetime
    ) -> Item:
        """改一样东西谁能看见。

        **放宽要先有一次点齐的点头**，收窄不用。这不是对称性的疏忽：
        共同素材是否发布由相关人决定（04 §1 权利矩阵），而收回自己的东西
        是权利，权利必须顺手（07 原则三）——要走流程才能收回的权利等于没有。

        助手在这条路径上永远被拒，连起草都不行：`publish_artifact`
        属于"永远需要真人"的那一档（02 §7.4）。
        """
        item, kind = self._load(item_id)
        if REACH not in kind.required_extras:
            raise IllegalMove(f"{kind.key} 没有可见范围这回事")
        if by.is_agent:
            raise AgentCannotDecide("往外发这件事永远要真人决定")
        if item.awaiting_a_person:
            raise DraftDoesNotCount("还没人认的草稿谈不上发不发")

        current = Reach(item.extras.get(REACH, Reach.OURS))
        if to is Reach.OUTSIDE and current is Reach.OURS and not self._cleared(item.id):
            raise NotYoursToDecide("发到外面去，得相关的人先点过头")

        extras = dict(item.extras)
        extras[REACH] = to.value
        return self._save(replace(item, extras=extras, updated_at=now))

    # --- 读 ---

    def view(
        self, *, now: datetime, names: Mapping[UUID, str] | None = None
    ) -> CanvasView:
        """一屏。`names` 给了才说得出"还差陈牧和苏晚点头"，没给就只说人数。"""
        items = self._repo.list_items(self._space.id)
        cards: list[Card] = []
        gates: list[Card] = []
        stuck: list[Card] = []
        drafts: list[Card] = []
        done = total = 0

        for item in items:
            kind = self._kinds.get(item.kind)
            card = Card(item, kind.label, self._notice(item, kind, now=now, names=names))
            if item.awaiting_a_person:
                # 助手关掉之后这一栏是空的：草稿不算数，也就不该继续占着屏幕。
                # 行还在库里，重新打开助手它们原样回来。
                if self._space.agent_enabled and item.state != DISCARDED:
                    drafts.append(card)
                continue
            if not _effective(item):
                continue
            cards.append(card)
            if kind.needs_human_decision and item.state not in kind.done_states:
                gates.append(card)
            if kind.counts_toward_progress:
                total += 1
                if item.state in kind.done_states:
                    done += 1
                elif item.assignee_id is None or (
                    item.due_at is not None and item.due_at <= now
                ):
                    # 没人负责，或者过了说好的时间——这两样都是"卡住"。
                    # 一件事只要没有名字挂在上面，它就不会自己往前走。
                    stuck.append(card)

        progress = Progress(done=done, total=total)
        return CanvasView(
            title=self._space.name,
            cards=tuple(cards),
            open_gates=tuple(gates),
            stuck=tuple(stuck),
            drafts=tuple(drafts),
            progress=progress,
            summary=_summary(progress, len(gates), len(stuck), len(drafts)),
        )

    def item(self, item_id: UUID) -> Item:
        """按 id 取一条，被丢掉的和没人认的也取得到。

        取不到就报错，不返回 None——"不在这个空间里"和"这条不算数"
        是两件事，混成同一个返回值，调用方就分不开了。
        """
        found, _ = self._load(item_id)
        return found

    def assigned_to(self, principal_id: UUID) -> tuple[Item, ...]:
        """某个人手上的活。

        助手起草而没人认的条目**不出现在这里**，哪怕它写了负责人——
        它写的负责人是个建议，不是一件落到别人头上的事。
        """
        return tuple(
            item
            for item in self._repo.list_items(self._space.id)
            if _effective(item) and item.assignee_id == principal_id
        )

    # --- 内部 ---

    def _load(self, item_id: UUID) -> tuple[Item, ItemKind]:
        item = self._repo.get_item(item_id)
        if item is None or item.space_id != self._space.id:
            raise IllegalMove(f"这个空间里没有 {item_id}")
        return item, self._kinds.get(item.kind)

    def _save(self, item: Item) -> Item:
        self._repo.save_item(item)
        return item

    def _agent_may_draft(self, kind: ItemKind) -> None:
        self._assistant_channel_open()
        if not kind.agent_may_draft:
            raise AgentCannotDecide(f"{kind.key} 这一类不接受助手起草")

    def _assistant_channel_open(self) -> None:
        if not self._space.agent_enabled:
            raise AgentIsOff("助手被关掉了")

    def _a_person(self, by: Actor, doing: str) -> None:
        if by.is_agent:
            raise AgentCannotDecide(f"助手不能{doing}自己写的东西")

    def _may_change(self, item: Item, by: Actor) -> None:
        """谁能改一条已经在画布上的东西。

        真人改自己的、改别人的都行——这是共同拥有的空间，不是各自的文件夹。
        助手只能改**自己起草且还没人认**的那些：被采纳的那一刻，
        那条就成了真人的决定，助手再动它就是替人改主意。
        """
        if by.is_agent:
            self._assistant_channel_open()
            if not item.awaiting_a_person:
                raise AgentCannotDecide("这条已经是真人的决定了，助手改不了")
            return
        if item.state == DISCARDED:
            raise IllegalMove("丢掉的东西不再参与")
        if item.awaiting_a_person:
            raise DraftDoesNotCount("先采纳，再改——不然改的是一件不算数的事")

    def _cleared(self, about: UUID) -> bool:
        """有没有一次关于这条的、已经点齐的点头。"""
        for item in self._repo.list_items(self._space.id):
            kind = self._kinds.get(item.kind)
            if not kind.needs_human_decision or not _effective(item):
                continue
            if item.state in kind.done_states and item.extras.get(ABOUT) == str(about):
                return True
        return False

    def _notice(
        self,
        item: Item,
        kind: ItemKind,
        *,
        now: datetime,
        names: Mapping[UUID, str] | None,
    ) -> str | None:
        """卡片上那句给人看的话。

        用户词，不是领域词（07 §2）。短句，一次说一件事，不用感叹号。
        没什么要说的时候返回 None——每张卡都挂一句话等于每张卡都没话说。
        """
        if item.awaiting_a_person:
            return "这是我猜的，你看对不对"
        if kind.needs_human_decision and item.state not in kind.done_states:
            waiting = [
                u
                for u in _uuids(item.extras, DECIDERS)
                if u not in set(_uuids(item.extras, CONFIRMED_BY))
            ]
            if names is not None and all(u in names for u in waiting):
                return f"还差{_and_join([names[u] for u in waiting])}点头"
            return f"还差 {len(waiting)} 个人点头"
        if kind.counts_toward_progress and item.state not in kind.done_states:
            if item.due_at is not None and item.due_at <= now:
                return "已经过了说好的时间"
            if item.assignee_id is None:
                return "还没人认领"
        return None


def _effective(item: Item) -> bool:
    """这条算不算数。

    两种不算：被丢掉的，和助手起草而没人认的。后者是"AI 起草，人类决定"
    在这一层的全部含义——它既不计入做完了多少，也不落到任何人头上，
    也做不了任何决定的结论。
    """
    return item.state != DISCARDED and not item.awaiting_a_person


def _uuids(extras: Mapping[str, Any], key: str) -> tuple[UUID, ...]:
    raw = extras.get(key) or []
    if not isinstance(raw, list):
        raise MissingProvenance(f"{key} 得是一串人")
    try:
        return tuple(u if isinstance(u, UUID) else UUID(str(u)) for u in raw)
    except ValueError as exc:
        raise MissingProvenance(f"{key} 里有认不出来的人：{exc}") from None


def _and_join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return "、".join(names[:-1]) + "和" + names[-1]


def _summary(progress: Progress, gates: int, stuck: int, drafts: int) -> str:
    """一句话概括这一屏。给的是件数，不是百分比——这个产品不做总分。"""
    parts = (
        [f"{progress.total} 件事做完 {progress.done} 件"]
        if progress.total
        else ["还没有要做的事"]
    )
    if gates:
        parts.append(f"{gates} 件事等着定")
    if stuck:
        parts.append(f"{stuck} 件卡住了")
    if drafts:
        parts.append(f"{drafts} 条等你过目")
    return "，".join(parts)
