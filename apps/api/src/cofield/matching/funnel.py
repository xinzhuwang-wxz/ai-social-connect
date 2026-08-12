"""撮合漏斗的前两段：硬过滤与召回。

```
两万人 ──权限+硬约束(SQL)──▶ 数千 ──语义召回──▶ 数十 ──▶ 求解（#6）
```

三条设计不能动：

**硬约束是过滤器，不参与打分。** 任何软分都不能抵消一条硬约束冲突。
时间凑不上就是凑不上，不能因为"技能特别合适"就放行。

**权限过滤必须前置。** 先召回后过滤会造成侧信道泄露——攻击者能从反复
查询的结果数量与时延差异反推隐藏字段。而且高选择性下 post-filter 的
召回会崩：两万人过滤到几千是个位数百分比的选择性，这时候对幸存者做精确
向量比较成本微不足道，正是 pgvector 最舒服的场景。

**语义降级不能拖垮整条链路。** 嵌入服务挂了，用户仍然要能拿到候选——
少了长尾表达那一路，但不是白屏。降级发生了就写进 trace，让它可观测。

## 时间为什么不在这一段过滤

"我和他都周四有空"不等于"我们四个人都有连着两段"。整组共同空闲是**群体
属性**，只有拿到具体分组才算得出来——这是超图那件事的直接后果。实测也
支持这个分工：任意一段重合几乎总能凑上（四人组 300 次里 285+ 次），连续
两段只有约一半。放在这里过滤形同虚设，放在求解器里才咬得动。

所以这一段里时间只作**排序信号**，真正的时间硬约束由求解器施加。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.sql import Select

from cofield.adapters.persistence.schema import event_members, principals
from cofield.domain.model.intent import IntentSignal, Reach
from cofield.domain.ports.embedder import EmbeddingUnavailable
from cofield.matching.semantic import SemanticRetriever

WEEK_SLOTS = 21

#: 语义排序之后交给结构化排序的人数。比最终 40 大一个量级——
#: 语义负责**筛掉明显不搭的**，最终取舍留给能解释每一条依据的排序与求解。
SEMANTIC_KEEP = 200

#: 没有语义那一路时，从硬过滤结果里取多少个。这是个**任意的截断**，
#: 也正是纯结构化召回的局限：它没有任何理由认为前 500 个比后 500 个更合适。
STRUCTURED_CAP = 500


class RecallMode(StrEnum):
    """这次召回是怎么完成的。

    它要出现在界面上——"五态齐全"里的降级态，靠的就是它。
    用户有权知道这次匹配是不是打了折。
    """

    #: 语义参与了排序。
    SEMANTIC = "semantic"
    #: 嵌入服务不可用，退回纯结构化。长尾表达这次没被考虑。
    DEGRADED = "degraded"
    #: 本来就没配语义（或没人写过自述），不算故障。
    STRUCTURED = "structured"


@dataclass(frozen=True, slots=True)
class Candidate:
    principal_id: UUID
    display_name: str
    skills: tuple[str, ...]
    availability: str
    zone: str | None
    is_synthetic: bool
    #: 语义命中的原话。**成局证明引用它，不引用相似度**——
    #: "他自己写的『文风比较冲』"是用户能判断的理由，0.71 不是。
    matched_text: str | None = None


@dataclass(frozen=True, slots=True)
class FunnelTrace:
    """每一段剩多少，以及这次是怎么召回的。

    它不是调试输出——「凑不出队」时要靠它告诉用户是**哪一段**把人筛没了，
    以及放宽哪一项能多出多少人。
    """

    population: int
    after_hard_filter: int
    after_recall: int
    blocked_by: tuple[str, ...] = ()
    recall_mode: RecallMode = RecallMode.STRUCTURED


@dataclass(frozen=True, slots=True)
class Shortlist:
    candidates: tuple[Candidate, ...]
    trace: FunnelTrace


def contiguous_common_slots(masks: list[str], *, run: int = 2) -> int:
    """整组有多少个「连续 run 段」的共同空闲。

    实测：任意一段重合几乎总能凑上，连续两段才是真约束——
    4 人组 50%，5 人组 27%。所以时间约束按这个算，不按单段算。
    """
    if not masks:
        return 0
    common = [all(m[i] == "1" for m in masks) for i in range(WEEK_SLOTS)]
    return sum(
        all(common[i + k] for k in range(run)) for i in range(WEEK_SLOTS - run + 1)
    )


class Funnel:
    def __init__(
        self,
        conn: Connection,
        campus_id: str,
        *,
        retriever: SemanticRetriever | None = None,
    ) -> None:
        self._conn = conn
        self._campus = campus_id
        self._retriever = retriever

    def shortlist(
        self,
        intent: IntentSignal,
        *,
        now: datetime,
        exclude: frozenset[UUID] = frozenset(),
        keep: int = 40,
    ) -> Shortlist:
        """从全校筛到几十个候选，并记录每一段的量级。"""
        population = self._conn.execute(
            sa.select(sa.func.count()).select_from(principals)
        ).scalar_one()

        survivors = self._hard_filter_query(intent, exclude)
        after_hard = self._conn.execute(
            sa.select(sa.func.count()).select_from(survivors.subquery())
        ).scalar_one()

        blocked: list[str] = []
        if not after_hard:
            blocked = self._diagnose(intent, exclude=exclude)
            return Shortlist(
                candidates=(),
                trace=FunnelTrace(
                    population=population,
                    after_hard_filter=0,
                    after_recall=0,
                    blocked_by=tuple(blocked),
                    recall_mode=RecallMode.STRUCTURED,
                ),
            )

        pool, order, mode = self._recall_pool(intent, survivors)
        recalled = self._rank(intent, pool, order, keep=keep)

        return Shortlist(
            candidates=tuple(recalled),
            trace=FunnelTrace(
                population=population,
                after_hard_filter=after_hard,
                after_recall=len(recalled),
                recall_mode=mode,
            ),
        )

    # --- 第一段：硬约束 SQL 过滤 ---

    def _id_query(
        self, intent: IntentSignal, exclude: frozenset[UUID]
    ) -> Select[tuple[UUID]]:
        stmt = sa.select(principals.c.id).where(
            principals.c.id != intent.principal_id
        )
        if exclude:
            stmt = stmt.where(principals.c.id.not_in(exclude))
        return stmt

    def _hard_filter_query(
        self,
        intent: IntentSignal,
        exclude: frozenset[UUID] = frozenset(),
        *,
        skip: str | None = None,
    ) -> Select[tuple[UUID]]:
        """带上全部硬约束的 id 查询。

        `skip` 用于阻塞诊断与放宽估算——卸掉某一条看还剩多少人。
        它不是给正常路径用的，正常路径一条都不能卸。
        """
        stmt = self._id_query(intent, exclude)
        content = intent.content

        # 必要角色：会这一项的人，**或者说过想参与这类事的人**。
        #
        # 只认 `skills` 是不够的。一个刚做完一件事、想再接一个的人要的
        # 不是发起，是参与——他补不上任何一个具体的洞，但他正是这个产品
        # 该找到的人。只认 `skills` 的时候他永远不会出现在任何人的候选里。
        #
        # 放宽的只有召回。求解器的 ROLE_COVERAGE 仍然只认 `skills`，
        # 所以他能被叫来一起做，但不会被当成会剪辑的人塞进剪辑那个坑里。
        # **放宽召回，不放宽承诺。**
        if content.needs and skip != "needs":
            wanted = list(content.needs)
            stmt = stmt.where(
                sa.or_(
                    principals.c.skills.overlap(wanted),
                    principals.c.open_to.overlap(wanted),
                )
            )

        # 只问一起做成过事的人。
        #
        # 「熟人」由**共同完成过的事**定义，不是好友列表，也不是平台觉得
        # 你们熟——不变量 7：关系图谱是共同事件的可重建投影，不是主观判定。
        #
        # 第一次用的人在这一档下会得到零个候选。那不是 bug，是这一档的
        # 真实含义；界面要在他选之前就说清楚。
        if intent.reach is Reach.KNOWN and skip != "reach":
            mine = (
                sa.select(event_members.c.event_id)
                .where(event_members.c.principal_id == intent.principal_id)
                .where(event_members.c.left_at.is_(None))
                .scalar_subquery()
            )
            stmt = stmt.where(
                principals.c.id.in_(
                    sa.select(event_members.c.principal_id)
                    .where(event_members.c.event_id.in_(mine))
                    .where(event_members.c.left_at.is_(None))
                )
            )

        # 校区：跨校区的活动多数人不会去。
        if content.location_scope and skip != "location_scope":
            zone = _zone_of(content.location_scope)
            if zone:
                stmt = stmt.where(
                    sa.or_(principals.c.zone == zone, principals.c.zone.is_(None))
                )

        return stmt

    def _diagnose(self, intent: IntentSignal, *, exclude: frozenset[UUID]) -> list[str]:
        """一条都没剩下时，逐个卸掉约束看是哪条把人筛没的。

        这是「凑不出队」那一屏的数据来源——要能说出放宽哪一项多出多少人，
        而不是只说"没找到"。
        """
        blocked: list[str] = []
        content = intent.content

        for field_name, present in (
            ("needs", bool(content.needs)),
            ("location_scope", bool(content.location_scope)),
            ("reach", intent.reach is Reach.KNOWN),
        ):
            if not present:
                continue
            relaxed = self._hard_filter_query(intent, exclude, skip=field_name)
            if self._conn.execute(relaxed.limit(1)).first():
                blocked.append(field_name)

        return blocked

    def relaxation_gain(self, intent: IntentSignal, field_name: str) -> int:
        """放宽某一项能多出多少候选。阻塞证明直接用这个数字。"""

        def count(stmt: Select[tuple[UUID]]) -> int:
            return self._conn.execute(
                sa.select(sa.func.count()).select_from(stmt.subquery())
            ).scalar_one()

        widened = count(self._hard_filter_query(intent, skip=field_name))
        current = count(self._hard_filter_query(intent))
        return max(0, widened - current)

    # --- 第二段：召回 ---

    def _recall_pool(
        self, intent: IntentSignal, survivors: Select[tuple[UUID]]
    ) -> tuple[list[Candidate], dict[UUID, int], RecallMode]:
        """从幸存者里取一批送去排序，并说清这批是怎么来的。

        走语义时取的是**语义上最贴近原话**的一批，并把名次一并带出来——
        名次在池子内部继续区分远近。只带"命中了"这个布尔位的话，语义就
        只在选池那一步起作用，池子里两百个人会变得无差别。

        没有语义时取的是 SQL 碰巧先返回的一批。这是个**任意截断**，
        它没有任何理由认为前五百个比后五百个更合适——这正是纯结构化召回
        的局限，也是语义那一路存在的理由。
        """
        if self._retriever is not None:
            try:
                hits = self._retriever.rank(
                    intent.raw_expression, survivors, keep=SEMANTIC_KEEP
                )
            except EmbeddingUnavailable:
                # 语义是增强不是前提。降级但不中断，并让降级可见。
                return (
                    self._fetch(survivors.limit(STRUCTURED_CAP)),
                    {},
                    RecallMode.DEGRADED,
                )
            if hits:
                texts = {h.subject_id: h.matched_text for h in hits}
                order = {h.subject_id: i for i, h in enumerate(hits)}
                pool = [
                    replace(c, matched_text=texts[c.principal_id])
                    for c in self._fetch_by_id(tuple(texts))
                ]
                return pool, order, RecallMode.SEMANTIC
            # 没有人写过自述，或这批人一个都没进索引。不是故障。

        return self._fetch(survivors.limit(STRUCTURED_CAP)), {}, RecallMode.STRUCTURED

    def _fetch(self, ids: Select[tuple[UUID]]) -> list[Candidate]:
        return self._rows_for(principals.c.id.in_(ids))

    def _fetch_by_id(self, ids: tuple[UUID, ...]) -> list[Candidate]:
        return self._rows_for(principals.c.id.in_(ids))

    def _rows_for(self, predicate: sa.ColumnElement[bool]) -> list[Candidate]:
        rows = self._conn.execute(
            sa.select(
                principals.c.id,
                principals.c.display_name,
                principals.c.skills,
                principals.c.availability,
                principals.c.zone,
                principals.c.is_synthetic,
            ).where(predicate)
        ).all()
        return [
            Candidate(
                principal_id=r.id,
                display_name=r.display_name,
                skills=tuple(r.skills),
                availability=r.availability or "1" * WEEK_SLOTS,
                zone=r.zone,
                is_synthetic=r.is_synthetic,
            )
            for r in rows
        ]

    def _rank(
        self,
        intent: IntentSignal,
        pool: list[Candidate],
        order: dict[UUID, int],
        *,
        keep: int,
    ) -> list[Candidate]:
        """从数百缩到数十。

        排序信号只有三个，**每一个都能写成一句给用户看的话**：

        - 补上了几个缺口 —— "他能补上缺的剪辑"
        - 语义有多贴近 —— "他自己写的『文风比较冲』"
        - 时间够不够宽裕 —— "你们有两段连着的共同空闲"

        缺口排在语义前面，因为缺口是用户**说出来的要求**，语义是**说不全的
        偏好**；要求没满足时，风格再合也没用。真正的取舍留给求解器，
        它的每一条依据都要能写进成局证明。

        名次用的是语义排序里的位置，不是相似度本身——浮点数会让同一份数据
        在不同机器上排出不同结果，而仿真结论必须能被重跑验证。
        """
        needs = set(intent.content.needs)
        mine = intent_owner_availability(intent)
        missed = len(order) + 1

        def rank(candidate: Candidate) -> tuple[int, int, int]:
            covered = len(needs & set(candidate.skills))
            closeness = order.get(candidate.principal_id, missed)
            slack = contiguous_common_slots([mine, candidate.availability])
            return (-covered, closeness, -slack)

        return sorted(pool, key=rank)[:keep]


def intent_owner_availability(intent: IntentSignal) -> str:
    """发起人的空闲。取不到时按全空处理——宁可多召回，让求解器去筛。"""
    return getattr(intent, "_owner_availability", "1" * WEEK_SLOTS)


def _zone_of(location_scope: str) -> str | None:
    for zone in ("东校区", "西校区", "南校区"):
        if zone in location_scope:
            return zone
    return None
