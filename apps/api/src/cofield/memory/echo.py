"""行动回声：证据变成可撤销的记忆切面。

## 为什么是「证据 → 草稿」而不是「一个空输入框」

事结束的那一刻没人想写小作文。给一个空框，多数人会跳过；跳过之后
这次协作就没有留下任何可核验的痕迹，下一次成局证明只能重新靠自述——
而自述正是这个产品从第一天起就不打算相信的东西。

所以草稿由**已经存在的事实**聚成：谁放了什么上来、这次做的是什么。
用户要做的是逐条决定留不留，不是从零开始写。

## 三条不能动的设计

**必须由本人逐项确认。** 系统抽出草稿，本人点过才算数。没点过的永远不
出现在任何人的证明里——这和助手草稿是同一条规则（04 权利矩阵：
「记忆切面是否生效」由被描述者决定，个人代理只能建议，场域智能体只生成草稿）。

**随时可撤销，撤销即时生效。** 撤销之后它从任何**新的**证明里消失。
机制不在这一层：它在 `MemoryRepository.citable()` 的 WHERE 里，
而那是切面进入证明的唯一入口。这一层只负责让撤销这个动作足够顺手。

**派生自证据，且指得回去。** 每条切面带着 `evidence_ids`。
一条说不出来源的记忆，本人无从判断该不该留着它。

## 抽不出来不是故障

模型不可用时 `draft_for` 返回空，本人照样能自己写一条。行动回声是**可选
体验**：拒绝、撤销或跳过它，都不影响事件的完成状态，也不影响未来的匹配
资格——这一层因此没有任何"必须先完成回声"的前置检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from cofield.adapters.persistence.memory import (
    EvidenceItem,
    FacetState,
    MemoryFacet,
    MemoryRepository,
)
from cofield.domain.ports.composer import (
    Composer,
    ComposerUnavailable,
    DraftKind,
)

#: 这一屏叫什么。领域里它是「行动回声」，屏幕上永远是这五个字（07 §2、§5）。
HEADLINE = "这次留下了什么"

#: 「记忆切面」在屏幕上的名字。
MY_RECORD = "我的经历"

#: AI 草稿的标识。照 07 §6 的对照表——不写 `approval_state: draft`，
#: 也不写"系统推断"。用户要一眼看出这句话是谁写的。
AGENT_DRAFT_HINT = "这是我猜的，你看对不对"

#: 撤销按钮上的字。两个字，不是「发起数据主体权利请求」——
#: 如果行使权利需要仪式感，用户就不会行使，而没人行使的权利等于不存在。
REVOKE_LABEL = "撤销"

#: 一件事上最多抽几条草稿给一个人看。
#:
#: 取一条不是偷懒：这一屏要用户逐条决定，而逐条决定的前提是条数少到
#: 他愿意一条条看。甩十条出来，人不会挑，只会全部跳过——那和没有回声一样。
MAX_DRAFTS = 1

#: 抽切面时给起草者的任务说明。**写死在代码里**，不从任何地方读取——
#: 它是指令，证据是数据，两者的来源必须能被静态区分（见 composer 端口）。
#:
#: "不要写名字"是有原因的：这句话将来会被拼进「周雨剪过一支 60 秒短片」
#: 这种句子里，名字由引用它的那一层按当时的授权决定说不说。
#: 让模型把名字写进切面文本，就等于把披露判断交给了模型。
FACET_INSTRUCTION = "只写他做成了什么，以动词开头，不要写名字，不要评价好坏，不超过 20 字。"

#: 写这次共同记录时给起草者的任务说明。
RECAP_INSTRUCTION = "写清楚这次一起做成了什么，最多两句，不要评价谁。"


class EchoRefused(Exception):
    """这次回声动作没有发生。"""


class NotYours(EchoRefused):
    """描述个人能力的切面只有本人能确认或撤销。

    别人替他背书，这条记忆就成了一次他没参与的判断——而它会影响
    这个人以后被怎么找到。
    """


class NothingToConfirm(EchoRefused):
    """没有可确认的东西：它不存在，或者已经不是草稿了。

    已撤销的切面走的也是这一条——撤销之后没有回到已确认的路径。
    """


@dataclass(frozen=True, slots=True)
class Recap:
    """这次一起做成了什么。

    **不入库。** 它是证据的一次转写，删掉重算还是它，存下来只会多一份
    可能和证据不一致的副本。要留下来的东西是切面，那个要本人点头。
    """

    text: str
    #: 依据了哪些事实，顺序与传给起草者的一致。用户点开逐条对照。
    grounded_in: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EchoDraft:
    """一条等着本人点头的草稿。

    `hint` 常驻：草稿和已确认的内容必须一眼可辨，而"一眼"的意思是
    它自己带着那句话，不是靠界面记得加一个角标。
    """

    facet: MemoryFacet
    grounded_in: tuple[str, ...]
    hint: str = AGENT_DRAFT_HINT


class ActionEcho:
    """一次共同行动结束之后的那一屏。"""

    def __init__(
        self,
        repo: MemoryRepository,
        *,
        composer: Composer,
    ) -> None:
        self._repo = repo
        self._composer = composer

    # --- 读 ---

    def gather(self, event_id: UUID) -> tuple[EvidenceItem, ...]:
        """这次留下的全部证据。屏幕上先出现的是它们，不是一个输入框。"""
        return tuple(self._repo.evidence_for(event_id))

    def my_record(self, principal_id: UUID) -> tuple[MemoryFacet, ...]:
        """「我的经历」：系统记住了什么、我点过什么、我收回过什么。"""
        return tuple(self._repo.for_principal(principal_id))

    # --- 起草 ---

    def recap(self, event_id: UUID) -> Recap | None:
        """把这次的证据写成一小段共同记录。

        起草失败返回 `None`，屏幕上就只剩证据本身——那已经足够回答
        "这次留下了什么"。共同记录是锦上添花，不是这一屏的前提。
        """
        facts = self._facts(event_id, mine=frozenset())
        if not facts:
            return None
        try:
            draft = self._composer.draft(
                DraftKind.ACTION_ECHO,
                facts=facts,
                instruction=RECAP_INSTRUCTION,
                max_chars=60,
            )
        except ComposerUnavailable:
            return None
        return Recap(text=draft.text, grounded_in=draft.grounded_in)

    def draft_for(
        self,
        *,
        event_id: UUID,
        principal_id: UUID,
        now: datetime,
    ) -> tuple[EchoDraft, ...]:
        """从证据里抽出这个人的一条草稿，落库为 `draft`。

        返回空元组的两种情况都不是错误：

        - 这次没有任何证据——那就没什么可抽的，闭嘴比编一句好。
        - 起草服务不可用——**降级**，本人仍然可以用 `write_own` 自己写一条。

        草稿一律 `drafted_by_agent=True`。它落库不是因为它算数，是因为
        本人下次打开这一屏还要看得到同一条；未确认的草稿进不了任何证明，
        这一点由 `citable()` 的 WHERE 保证，不由"我们记得别引用它"保证。
        """
        evidence = self._repo.evidence_for(event_id)
        if not evidence:
            return ()

        mine = frozenset(e.id for e in evidence if e.uploaded_by == principal_id)
        facts = self._facts(event_id, mine=mine, evidence=evidence)
        try:
            draft = self._composer.draft(
                DraftKind.FACET_EXTRACTION,
                facts=facts,
                instruction=FACET_INSTRUCTION,
                max_chars=30,
            )
        except ComposerUnavailable:
            # 降级：抽不出就不抽。这一屏照常，本人自己写的那条一样能用。
            return ()

        facet = MemoryFacet(
            id=uuid4(),
            principal_id=principal_id,
            text=draft.text,
            state=FacetState.DRAFT,
            created_at=now,
            event_id=event_id,
            # 指得回全部证据，不只是他自己放上来的那几件：这句话是从
            # 整件事里读出来的，只指自己那部分会让来源看起来比实际窄。
            evidence_ids=tuple(e.id for e in evidence),
            drafted_by_agent=True,
        )
        self._repo.add_facet(facet)
        return (EchoDraft(facet=facet, grounded_in=draft.grounded_in),)[:MAX_DRAFTS]

    # --- 本人的三个动作 ---

    def write_own(
        self,
        *,
        principal_id: UUID,
        text: str,
        now: datetime,
        event_id: UUID | None = None,
        evidence_ids: tuple[UUID, ...] = (),
    ) -> MemoryFacet:
        """本人自己写一条。

        它同样落成 `draft`，同样要 `confirm` 才生效。看起来多此一举——
        本人写的东西为什么还要本人再点一次？因为**只留一条通往 `confirmed`
        的路**：两条路意味着"哪些切面算数"这个问题有两个答案，
        而其中一个迟早会漏掉一个检查。界面上这两步可以是同一个按钮，
        它们都是本人的签名。

        `drafted_by_agent=False`：这句话是谁写的，数据里分得清。
        """
        stripped = text.strip()
        if not stripped:
            raise EchoRefused("空的一条留不下来")
        facet = MemoryFacet(
            id=uuid4(),
            principal_id=principal_id,
            text=stripped,
            state=FacetState.DRAFT,
            created_at=now,
            event_id=event_id,
            evidence_ids=evidence_ids,
            drafted_by_agent=False,
        )
        self._repo.add_facet(facet)
        return facet

    def confirm(self, facet_id: UUID, *, by: UUID, now: datetime) -> MemoryFacet:
        """本人点头。这是切面唯一能变成"算数"的动作。"""
        confirmed = self._repo.confirm(facet_id, by=by, now=now)
        if confirmed is not None:
            return confirmed
        raise self._explain(facet_id, by=by)

    def revoke(self, facet_id: UUID, *, by: UUID, now: datetime) -> MemoryFacet:
        """本人收回。下一次成局证明里就没有它了。

        不需要等任何异步任务：它从证明里消失靠的是 `citable()` 每次都
        重新读权威行，而不是靠某个清理任务追着删副本。已经发出去的证明
        带有效期，会自然过期——这条技术边界产品要诚实说明（04 §5.3）。
        """
        revoked = self._repo.revoke(facet_id, by=by, now=now)
        if revoked is not None:
            return revoked
        raise self._explain(facet_id, by=by)

    # --- 内部 ---

    def _explain(self, facet_id: UUID, *, by: UUID) -> EchoRefused:
        """条件更新没改到行，回头查一次是为了给出一句人能看懂的话。

        **判断本身已经在 WHERE 里做过了**，这里只负责措辞——
        如果反过来（先查再改），并发下两个请求会同时通过检查。
        """
        current = self._repo.get_facet(facet_id)
        if current is None:
            return NothingToConfirm("找不到这一条")
        if current.principal_id != by:
            return NotYours("这条不是你的，别人不能替你决定，你也不能替别人决定")
        return NothingToConfirm("这一条已经不是草稿了")

    def _facts(
        self,
        event_id: UUID,
        *,
        mine: frozenset[UUID],
        evidence: list[EvidenceItem] | None = None,
    ) -> tuple[str, ...]:
        """喂给起草者的封闭事实集合。

        每一条都来自我们自己的库：这次做的是什么、留下了哪几件东西、
        哪几件是他自己放上来的。**没有任何一条来自外部页面或对方 agent**，
        所以即使模型上当，它能拿到的也只有这些（见 composer 端口的说明）。

        `uploaded_by` 只用来分出"他自己放的"这一档，不落到文本里带名字——
        名字说不说由引用那一层按当时的授权决定。
        """
        items = self._repo.evidence_for(event_id) if evidence is None else evidence
        if not items:
            return ()
        facts: list[str] = []
        title = self._repo.event_title(event_id)
        if title:
            facts.append(f"这次一起做的是《{title}》")
        for item in items:
            body = f"（{item.body}）" if item.body else ""
            prefix = "他自己放上来的" if item.id in mine else "这次留下的"
            facts.append(f"{prefix}：{item.title}{body}")
        return tuple(facts)
