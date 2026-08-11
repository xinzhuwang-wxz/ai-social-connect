"""场域智能体：属于这次共同事件、由 N 名成员共同约束的助手。

它**不是**塞进群聊的第三个聊天对象，而是为这段关系增加的一个共同界面。
这个区别是可测的：它没有"自己的"看法，它说的每一句话都必须能指回
空间里已经存在的东西。

## 它拿不到任何凭证

模型进程手上没有数据库连接、没有对象存储、没有向量库、没有外网。
它能做的每一件事都要一张**能力令牌**，而令牌是这一层发的，不是它自己造的。

令牌绑三样：**哪个空间**（跨共域直接不可能）、**什么用途**（起草不能拿去
改承诺）、**哪个策略纪元**（成员一变旧令牌立刻作废）。

为什么纪元比"短过期"更要紧：过期能挡住很久以前发的令牌，挡不住三十秒前
发的、而这三十秒里有人退出了。撤销必须是即时的。

## 有副作用的事走五步

    待批准 → 确认需要谁 → 校验版本未变 → 执行 → 记录

助手自己只能走到第一步。第三步是防"它拿着三分钟前的读数去改现在的东西"——
中间有人动过，就必须重来。

## 关掉它，共域照常

这是 M3 的判据。助手是共域里的一张卡片，不是共域的运行时——
所以这一层的每一个入口在 `agent_enabled=False` 时都必须拒绝，
而共域的人工路径一条都不受影响（#10 那边有专门的用例走完全流程）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection

from cofield.adapters.persistence.schema import spaces
from cofield.domain.ports.composer import (
    Composer,
    ComposerUnavailable,
    DraftKind,
)
from cofield.space.canvas import AgentIsOff, Canvas, CanvasRefused, field_agent

#: 令牌活多久。短，但它不是主要的撤销手段——纪元才是。
#: 取十分钟是因为一次起草用不了那么久，而更短会让重试变成主要失败模式。
TOKEN_TTL = timedelta(minutes=10)

#: 一次给几条建议。
#:
#: 实证：搜索上限 3→100 时福利显著下降（Magentic Marketplace）。
#: 助手一次甩十条建议，人不会挑，只会全部忽略——那和没有助手一样，
#: 只是多占了屏幕。
MAX_SUGGESTIONS = 3


class Power(StrEnum):
    """令牌能干什么。**枚举而不是通配**——新增一种能力要显式加进来，
    顺带被迫回答"这一条为什么可以不经真人"。"""

    #: 读空间里已批准的对象。
    READ_APPROVED = "read_approved"
    #: 往画布上放草稿。草稿不算数，所以这一条不需要真人预先批准。
    DRAFT = "draft"


#: 助手**永远**不能拿到的能力，以及为什么。
#:
#: 注意它们一个都不在 `Power` 里——所以在类型层就**不可表示**，
#: 而不是"表示得出来但会被过滤掉"。这份清单是给人看的记录：
#: 让"没给"成为一个写下来的判断，而不是某天加功能时才发现的意外。
#:
#: 运行时那道检查仍然留着，挡的是动态拼出来的字符串（比如从配置读进来的
#: 能力名）。两道都在的理由是：类型检查管不了运行时喂进来的东西。
FORBIDDEN: dict[str, str] = {
    "commit": "改承诺——AI 可以代为表达，不能代为承诺",
    "membership": "增删成员——谁在这个组里是成员共同的事",
    "publish": "发布素材——发出去就收不回来了",
    "approve_memory": "批准记忆——它会影响这个人以后被怎么找到",
    "spend": "花钱、预订、取消",
    "cross_space": "读别的共域——存储命名空间是隔离的",
}


class CapabilityRefused(CanvasRefused):
    """令牌不管用。"""


@dataclass(frozen=True, slots=True)
class Capability:
    """一张短期、绑空间、绑用途、绑纪元的能力令牌。

    它是**值对象**，不是数据库行：发出去就没人管了，验证靠三个字段自己
    对得上，不靠去查一张吊销表。吊销表会引入"查的时候它还有效、
    用的时候已经无效"的窗口。
    """

    space_id: UUID
    powers: frozenset[Power]
    epoch: int
    expires_at: datetime
    #: 用途绑定。同一张令牌不能既用来起草提醒又用来起草记忆——
    #: 用途不绑死，"最小权限"就只是一句口号。
    purpose: DraftKind

    def allows(self, power: Power, *, purpose: DraftKind) -> bool:
        return power in self.powers and purpose is self.purpose


@dataclass(frozen=True, slots=True)
class Suggestion:
    """一条建议。**每条都能一键说「不用了」**——

    所以它必须是一条独立的东西，不能是一段话里的一句。
    混在一段话里，用户要么全接受要么全拒绝。
    """

    kind: str
    title: str
    #: 它是根据空间里的什么写的。用户点开能看到——
    #: **看不到依据的建议，"人类决定"就只是点一下按钮**。
    grounded_in: tuple[str, ...]
    #: 落进画布之后的条目 id。
    item_id: UUID | None = None


class FieldAgent:
    """一个共域的助手。它只认识这一个空间。"""

    def __init__(
        self,
        conn: Connection,
        canvas: Canvas,
        *,
        composer: Composer,
        campus_id: str,
    ) -> None:
        self._conn = conn
        self._canvas = canvas
        self._composer = composer
        self._campus = campus_id

    # --- 令牌 ---

    def issue(
        self, *, purpose: DraftKind, powers: frozenset[Power], now: datetime
    ) -> Capability:
        """发一张令牌。助手自己调不到这个方法——它没有连接。"""
        space = self._canvas.space
        if not space.agent_enabled:
            raise AgentIsOff("助手关着，不发令牌")
        # 用 `str(p)` 而不是 `p.value`：动态拼出来的能力名是普通字符串，
        # 对它取 `.value` 会抛 AttributeError——那会把一次"权限被拒"
        # 变成一次"服务出错"，两者的处理方式完全不同。
        asked = {str(getattr(p, "value", p)) for p in powers}
        forbidden = asked & set(FORBIDDEN)
        if forbidden:
            raise CapabilityRefused(f"这些能力永远不发：{sorted(forbidden)}")
        unknown = asked - {p.value for p in Power}
        if unknown:
            raise CapabilityRefused(f"不认识的能力：{sorted(unknown)}")
        return Capability(
            space_id=space.id,
            powers=powers,
            epoch=self._epoch(),
            expires_at=now + TOKEN_TTL,
            purpose=purpose,
        )

    def check(self, token: Capability, power: Power, *, now: datetime) -> None:
        """验一张令牌。三条都不过就是不过，没有"基本上对"。"""
        space = self._canvas.space
        if not space.agent_enabled:
            raise AgentIsOff("助手关着")
        if token.space_id != space.id:
            # 跨共域在这里被挡死。存储命名空间隔离不是靠"我们不会去查别的空间"。
            raise CapabilityRefused("这张令牌不是这个空间的")
        if token.epoch != self._epoch():
            raise CapabilityRefused("成员或策略变过了，这张令牌已经作废")
        if now >= token.expires_at:
            raise CapabilityRefused("令牌过期了")
        if power not in token.powers:
            raise CapabilityRefused(f"这张令牌没有 {power.value} 这项能力")

    def bump_epoch(self) -> int:
        """成员、提案、同意或策略变了，纪元 +1，所有旧令牌立刻作废。

        调用它的是那些**改变了谁在这个组里、谁同意了什么**的地方——
        不是助手自己。
        """
        bumped = self._conn.execute(
            sa.update(spaces)
            .where(spaces.c.id == self._canvas.space.id)
            .values(policy_epoch=spaces.c.policy_epoch + 1)
            .returning(spaces.c.policy_epoch)
        ).scalar_one()
        return int(bumped)

    # --- 它能做的事 ---

    def suggest_next_steps(
        self,
        token: Capability,
        *,
        now: datetime,
        limit: int = MAX_SUGGESTIONS,
    ) -> tuple[Suggestion, ...]:
        """看一眼空间，起草几条下一步。

        **只读已批准的对象**——未采纳的草稿（包括它自己上次写的）不作数，
        否则助手会开始引用自己，越写越远。

        起草失败**不是错误**：降级成空建议，共域照常。助手是增强不是前提。
        """
        self.check(token, Power.READ_APPROVED, now=now)
        self.check(token, Power.DRAFT, now=now)

        facts = self._approved_facts(now=now)
        if not facts:
            # 空空的空间里助手无话可说，这时候闭嘴比编一条"欢迎开始协作"好。
            return ()

        try:
            draft = self._composer.draft(
                token.purpose,
                facts=facts,
                instruction="给出接下来最该做的一件具体的事，一句话，不要客套。",
                max_chars=40,
            )
        except ComposerUnavailable:
            # 降级：说不出话就不说。共域的人工路径一条都不受影响。
            return ()

        suggestion = Suggestion(
            kind="task",
            title=draft.text,
            grounded_in=draft.grounded_in,
        )
        return (suggestion,)[:limit]

    def put_on_canvas(
        self, token: Capability, suggestion: Suggestion, *, now: datetime
    ) -> Suggestion:
        """把建议放进画布，标成**助手起草、尚未采纳**。

        这是助手能走到的最后一步。真人不采纳，它就一直不算数——
        不进完成度、不落任何人待办、做不了任何结论。
        """
        self.check(token, Power.DRAFT, now=now)
        if not suggestion.grounded_in:
            # 没有依据的建议不许上画布。它会让"点开看依据"这个动作
            # 变成有时有东西有时没有，而那等于这个承诺不成立。
            raise CapabilityRefused("没有依据的建议不上画布")

        item = self._canvas.add(
            suggestion.kind,
            suggestion.title,
            by=field_agent(self._canvas.space.id),
            now=now,
        )
        return Suggestion(
            kind=suggestion.kind,
            title=suggestion.title,
            grounded_in=suggestion.grounded_in,
            item_id=item.id,
        )

    # --- 内部 ---

    def _epoch(self) -> int:
        epoch = self._conn.execute(
            sa.select(spaces.c.policy_epoch).where(
                spaces.c.id == self._canvas.space.id
            )
        ).scalar_one()
        return int(epoch)

    def _approved_facts(self, *, now: datetime) -> tuple[str, ...]:
        """助手看得到的全部：这个空间里**已批准**的条目标题。

        它看不到任何人的私有记忆，也看不到别的共域——不是因为我们没写
        那段查询，是因为它手上只有这一个空间的 canvas，而 canvas 自己
        受 RLS 约束。
        """
        # 只看 `cards`：那一栏里的东西都是算数的。`drafts` 是它自己上次写的、
        # 还没人认领的，读进来它就会开始引用自己，越写越远。
        view = self._canvas.view(now=now)
        return tuple(
            card.item.title for card in view.cards if card.item.title.strip()
        )
