"""证据与记忆切面的仓储。

## 这一层守住三条，全部靠 SQL 而不是靠调用方记得

**只有 `confirmed` 能被引用。** `citable()` 是切面进入任何一份成局证明的
**唯一**入口，它在 WHERE 里写死 `state = 'confirmed' AND revoked_at IS NULL`。
没有第二条路：没有缓存、没有把切面文本抄进别处的派生表、没有"先查出来
再由调用方过滤"的形状。因此"撤销即时生效"不是一条约定，是一次 UPDATE
之后下一次查询必然读不到——两者之间不存在任何可以变旧的副本。

**确认与撤销都写在 WHERE 里。** `confirm()` 带着 `principal_id = by` 与
`state = 'draft'` 两个条件做条件更新，不是"先查一下是不是本人再改"。
先查后改在并发下两个请求会同时通过检查；更要紧的是，权限判断放在
WHERE 里意味着**它不可能被忘记**，而放在 if 里意味着它只是碰巧写了。

**关系强度是查出来的，不是存下来的。** `co_completed()` 从 `event_members`
这条超边投影出"这批人一起做完过哪几件事"。库里没有任何一列叫熟悉度、
亲密度或好友分——不变量 7 说关系图谱是共同事件的可重建投影，
一旦它变成一个被维护的字段，"可重建"就成了假话。

## 为什么 `evidence` 里没有一列能放评价

它只存"谁、什么时候、放了什么、指向哪件事"。一旦多出一列打分，
这张表就变成了打分系统，而打分系统会让人不敢参加自己不擅长的事——
产品要的是"更可核验"，不是"分数更高"。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from .schema import event_members, evidence, memory_facets, principals, shared_events


class FacetState(StrEnum):
    """一条记忆的三种处境。

    刻意**没有**"已删除但还在用"这一档：那正是撤销权变成一纸空文的方式。
    """

    #: 系统抽的，或本人刚写下的。**任何人的证明里都不会出现它。**
    DRAFT = "draft"
    #: 本人点过头。只有这一档能被引用。
    CONFIRMED = "confirmed"
    #: 本人收回过的话。没有回到 `CONFIRMED` 的路径——收回就是收回。
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """一次共同行动留下的一件东西。

    **是事实，不是评价。** 这个类型里没有任何字段能放"谁表现好"，
    表里也没有——不是因为我们暂时没实现，是因为它不该存在。
    """

    id: UUID
    event_id: UUID
    kind: str
    title: str
    uploaded_by: UUID
    created_at: datetime
    body: str | None = None
    uri: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFacet:
    """一个人身上可撤销的一句话。"""

    id: UUID
    principal_id: UUID
    text: str
    state: FacetState
    created_at: datetime
    event_id: UUID | None = None
    #: 派生自哪些证据。空表示这条是本人自己写的。
    evidence_ids: tuple[UUID, ...] = ()
    drafted_by_agent: bool = False
    confirmed_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def citable(self) -> bool:
        """能不能被引用。

        两个条件而不是一个：`state` 是开关，`revoked_at` 是事实。
        只满足其中一个的行是坏数据，坏数据也不许被引用——
        这一条和 `MemoryRepository.citable()` 的 WHERE 是同一个判断，
        写两遍是因为对象和查询会各自被别人调用。
        """
        return self.state is FacetState.CONFIRMED and self.revoked_at is None


@dataclass(frozen=True, slots=True)
class CitedFacet:
    """一条**已经获准**被这次成局引用的切面。

    它和 `MemoryFacet` 分成两个类型，是因为它们回答不同的问题：
    前者是"本人手上有什么"，后者是"这一次允许说出口的是哪几条"。
    合成一个类型，"没获准的那条为什么没出现"就只能靠读代码来回答。
    """

    facet_id: UUID
    principal_id: UUID
    display_name: str
    text: str
    event_id: UUID | None
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class TogetherBefore:
    """这批人一起做完过的一件事。

    它是从超边投影出来的一行查询结果，**不是**库里的一条关系记录。
    重算一次就得到同样的结果，删掉向量与图投影也能重建。
    """

    event_id: UUID
    title: str
    formed_at: datetime


def _to_evidence(row: Row[Any]) -> EvidenceItem:
    return EvidenceItem(
        id=row.id,
        event_id=row.event_id,
        kind=row.kind,
        title=row.title,
        uploaded_by=row.uploaded_by,
        created_at=row.created_at,
        body=row.body,
        uri=row.uri,
    )


def _to_facet(row: Row[Any]) -> MemoryFacet:
    return MemoryFacet(
        id=row.id,
        principal_id=row.principal_id,
        text=row.text,
        state=FacetState(row.state),
        created_at=row.created_at,
        event_id=row.event_id,
        evidence_ids=tuple(row.evidence_ids or ()),
        drafted_by_agent=row.drafted_by_agent,
        confirmed_at=row.confirmed_at,
        revoked_at=row.revoked_at,
    )


class MemoryRepository:
    """租户由连接绑定（见 `engine.campus_connection`），这里不写 WHERE campus。

    `campus_id` 仍然要传：写入时那一列必须填对，填错会被策略的 WITH CHECK
    直接拒掉——越租户写入应该是数据库层的错误，不是应用层记得加过滤的结果。
    """

    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    # --- 证据 ---

    def add_evidence(self, item: EvidenceItem) -> None:
        self._conn.execute(
            sa.insert(evidence).values(
                id=item.id,
                campus_id=self._campus,
                event_id=item.event_id,
                kind=item.kind,
                title=item.title,
                body=item.body,
                uri=item.uri,
                uploaded_by=item.uploaded_by,
                created_at=item.created_at,
            )
        )

    def evidence_for(self, event_id: UUID) -> list[EvidenceItem]:
        """一件事上的全部证据，按放上来的先后。

        顺序不按贡献者也不按"重要程度"排——那两种排法都需要一个评分，
        而这张表里没有评分，也不该有。
        """
        rows = self._conn.execute(
            sa.select(evidence)
            .where(evidence.c.event_id == event_id)
            .order_by(evidence.c.created_at.asc(), evidence.c.id.asc())
        ).all()
        return [_to_evidence(r) for r in rows]

    def event_title(self, event_id: UUID) -> str | None:
        return self._conn.execute(
            sa.select(shared_events.c.title).where(shared_events.c.id == event_id)
        ).scalar_one_or_none()

    # --- 切面 ---

    def add_facet(self, facet: MemoryFacet) -> None:
        """写入一条切面。

        **没有 `state` 参数可以让调用方直接写 `confirmed`**——不是，
        它有：`facet.state` 就是。这里不拦，因为拦不住（调用方总能构造对象）。
        真正的保证在别处：`confirm()` 是唯一带 `confirmed_at` 的路径，
        而 `citable()` 只认 `state` 与 `revoked_at`。一条没经过 `confirm()`
        就被塞成 `confirmed` 的行，在审计里立刻显形——它没有确认时刻。
        """
        self._conn.execute(
            sa.insert(memory_facets).values(
                id=facet.id,
                campus_id=self._campus,
                principal_id=facet.principal_id,
                event_id=facet.event_id,
                text=facet.text,
                evidence_ids=list(facet.evidence_ids),
                state=facet.state.value,
                drafted_by_agent=facet.drafted_by_agent,
                confirmed_at=facet.confirmed_at,
                revoked_at=facet.revoked_at,
                created_at=facet.created_at,
            )
        )

    def get_facet(self, facet_id: UUID) -> MemoryFacet | None:
        row = self._conn.execute(
            sa.select(memory_facets).where(memory_facets.c.id == facet_id)
        ).one_or_none()
        return _to_facet(row) if row is not None else None

    def for_principal(self, principal_id: UUID) -> list[MemoryFacet]:
        """「我的经历」那一屏的数据源。

        **草稿、已确认、已撤销全都返回。** 本人要看得见系统猜了什么、
        自己点过什么、收回过什么——只给已确认的那部分，
        "系统记住了什么"这个问题就永远答不完整（04 §5.1）。
        """
        rows = self._conn.execute(
            sa.select(memory_facets)
            .where(memory_facets.c.principal_id == principal_id)
            .order_by(memory_facets.c.created_at.desc(), memory_facets.c.id.desc())
        ).all()
        return [_to_facet(r) for r in rows]

    def confirm(self, facet_id: UUID, *, by: UUID, now: datetime) -> MemoryFacet | None:
        """本人点头。返回 `None` 表示这次确认没有发生。

        两个条件都写在 WHERE 里：

        - `principal_id = by`——描述个人能力的切面**只有本人**能确认，
          别人替他背书这件事在 SQL 层就不成立，不靠上层记得判断。
        - `state = 'draft'`——撤销过的回不来。少了这一条，
          "撤销"就退化成"暂时不用"。
        """
        row = self._conn.execute(
            sa.update(memory_facets)
            .where(memory_facets.c.id == facet_id)
            .where(memory_facets.c.principal_id == by)
            .where(memory_facets.c.state == FacetState.DRAFT.value)
            .values(state=FacetState.CONFIRMED.value, confirmed_at=now)
            .returning(*memory_facets.c)
        ).one_or_none()
        return _to_facet(row) if row is not None else None

    def revoke(self, facet_id: UUID, *, by: UUID, now: datetime) -> MemoryFacet | None:
        """本人收回。返回 `None` 表示这次撤销没有发生。

        不限 `state`：草稿也能扔掉，已确认的也能收回。撤销必须顺手——
        一个需要走流程才能行使的权利等于不存在（07 原则三）。

        `revoked_at IS NULL` 那一条让重复撤销变成幂等的空操作，
        而不是把撤销时刻改成第二次点击的时间。
        """
        row = self._conn.execute(
            sa.update(memory_facets)
            .where(memory_facets.c.id == facet_id)
            .where(memory_facets.c.principal_id == by)
            .where(memory_facets.c.revoked_at.is_(None))
            .values(state=FacetState.REVOKED.value, revoked_at=now)
            .returning(*memory_facets.c)
        ).one_or_none()
        return _to_facet(row) if row is not None else None

    def citable(
        self,
        principal_ids: Sequence[UUID],
        *,
        permitted: frozenset[UUID],
    ) -> list[CitedFacet]:
        """切面进入成局证明的**唯一**入口。

        `permitted` 来自匹配信封的 `cited_facet_ids`：切面的授权粒度是
        **逐条**，不是字段级，所以它不走 `visible_fields` 那套翻译。
        传空集就是什么都引用不到——**默认拒绝**，不是"忘了传就全放行"。

        三道过滤缺一不可，而且都在 SQL 里：
        `state = 'confirmed'`（没点过头的不算）、`revoked_at IS NULL`
        （收回过的不算）、`id = ANY(permitted)`（这次没授权的不算）。
        """
        if not principal_ids or not permitted:
            return []
        rows = self._conn.execute(
            sa.select(
                memory_facets.c.id,
                memory_facets.c.principal_id,
                memory_facets.c.event_id,
                memory_facets.c.text,
                memory_facets.c.evidence_ids,
                principals.c.display_name,
            )
            .select_from(
                memory_facets.join(
                    principals, principals.c.id == memory_facets.c.principal_id
                )
            )
            .where(memory_facets.c.principal_id.in_(list(principal_ids)))
            .where(memory_facets.c.id.in_(sorted(permitted)))
            .where(memory_facets.c.state == FacetState.CONFIRMED.value)
            .where(memory_facets.c.revoked_at.is_(None))
            .order_by(memory_facets.c.confirmed_at.asc(), memory_facets.c.id.asc())
        ).all()
        return [
            CitedFacet(
                facet_id=r.id,
                principal_id=r.principal_id,
                display_name=r.display_name,
                text=r.text,
                event_id=r.event_id,
                evidence_ids=tuple(r.evidence_ids or ()),
            )
            for r in rows
        ]

    # --- 超边投影 ---

    def co_completed(self, member_ids: Sequence[UUID]) -> list[TogetherBefore]:
        """这批人**全都**在场、并且已经做完的事。

        `HAVING count(DISTINCT principal_id) = len(member_ids)` 是超边语义的
        全部：一件事要么把这几个人一起连上，要么不算数。拆成两两关系去数
        "共同好友"会把三个人各自参加过的三件不同的事，数成一次共同经历。

        `left_at IS NULL` 排除中途退出的人——他留在表里（关系边不能凭空消失），
        但"我们一起做完过"这句话对他不成立。
        """
        if not member_ids:
            return []
        ids = list(dict.fromkeys(member_ids))
        rows = self._conn.execute(
            sa.select(
                shared_events.c.id,
                shared_events.c.title,
                shared_events.c.formed_at,
            )
            .select_from(
                event_members.join(
                    shared_events, shared_events.c.id == event_members.c.event_id
                )
            )
            .where(event_members.c.principal_id.in_(ids))
            .where(event_members.c.left_at.is_(None))
            .where(shared_events.c.state == "completed")
            .group_by(
                shared_events.c.id, shared_events.c.title, shared_events.c.formed_at
            )
            .having(sa.func.count(sa.distinct(event_members.c.principal_id)) == len(ids))
            .order_by(shared_events.c.formed_at.desc(), shared_events.c.id.asc())
        ).all()
        return [
            TogetherBefore(event_id=r.id, title=r.title, formed_at=r.formed_at)
            for r in rows
        ]
