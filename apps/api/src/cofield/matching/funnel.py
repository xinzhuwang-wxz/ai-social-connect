"""撮合漏斗的前两段：硬过滤与召回。

```
两万人 ──权限+硬约束(SQL)──▶ 数百 ──混合召回──▶ 数十 ──▶ 求解（#6）
```

两条设计不能动：

**硬约束是过滤器，不参与打分。** 任何软分都不能抵消一条硬约束冲突。
时间凑不上就是凑不上，不能因为"技能特别合适"就放行。

**权限过滤必须前置。** 先召回后过滤会造成侧信道泄露——攻击者能从反复
查询的结果数量与时延差异反推隐藏字段。而且高选择性下 post-filter 的
召回会崩：两万人过滤到几百是 1.5% 选择性，这时候对几百个向量做精确
比较成本微不足道，正是 pgvector 最舒服的场景。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection

from cofield.adapters.persistence.schema import principals
from cofield.domain.model.intent import IntentSignal

WEEK_SLOTS = 21


@dataclass(frozen=True, slots=True)
class Candidate:
    principal_id: UUID
    display_name: str
    skills: tuple[str, ...]
    availability: str
    zone: str | None
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class FunnelTrace:
    """每一段剩多少。

    它不是调试输出——「凑不出队」时要靠它告诉用户是**哪一段**把人筛没了，
    以及放宽哪一项能多出多少人。
    """

    population: int
    after_hard_filter: int
    after_recall: int
    blocked_by: tuple[str, ...] = ()


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
    def __init__(self, conn: Connection, campus_id: str) -> None:
        self._conn = conn
        self._campus = campus_id

    def shortlist(
        self,
        intent: IntentSignal,
        *,
        now: datetime,
        exclude: frozenset[UUID] = frozenset(),
        limit: int = 500,
    ) -> Shortlist:
        """从全校筛到几十个候选，并记录每一段的量级。"""
        population = self._conn.execute(
            sa.select(sa.func.count()).select_from(principals)
        ).scalar_one()

        hard = self._hard_filter(intent, exclude=exclude, limit=limit)
        blocked: list[str] = []
        if not hard:
            blocked = self._diagnose(intent, exclude=exclude)

        recalled = self._recall(intent, hard)

        return Shortlist(
            candidates=tuple(recalled),
            trace=FunnelTrace(
                population=population,
                after_hard_filter=len(hard),
                after_recall=len(recalled),
                blocked_by=tuple(blocked),
            ),
        )

    # --- 第一段：硬约束 SQL 过滤 ---

    def _base_query(self, intent: IntentSignal, exclude: frozenset[UUID]):  # type: ignore[no-untyped-def]
        stmt = sa.select(
            principals.c.id,
            principals.c.display_name,
            principals.c.skills,
            principals.c.availability,
            principals.c.zone,
            principals.c.is_synthetic,
        ).where(principals.c.id != intent.principal_id)

        if exclude:
            stmt = stmt.where(principals.c.id.not_in(exclude))
        return stmt

    def _hard_filter(
        self, intent: IntentSignal, *, exclude: frozenset[UUID], limit: int
    ) -> list[Candidate]:
        stmt = self._base_query(intent, exclude)
        content = intent.content

        # 必要角色：候选至少覆盖一个缺口，否则他来了也补不上洞。
        if content.needs:
            stmt = stmt.where(principals.c.skills.overlap(list(content.needs)))

        # 校区：跨校区的活动多数人不会去。
        if content.location_scope:
            zone = _zone_of(content.location_scope)
            if zone:
                stmt = stmt.where(
                    sa.or_(principals.c.zone == zone, principals.c.zone.is_(None))
                )

        rows = self._conn.execute(stmt.limit(limit)).all()
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

    def _diagnose(self, intent: IntentSignal, *, exclude: frozenset[UUID]) -> list[str]:
        """一条都没剩下时，逐个卸掉约束看是哪条把人筛没的。

        这是「凑不出队」那一屏的数据来源——要能说出放宽哪一项多出多少人，
        而不是只说"没找到"。
        """
        blocked: list[str] = []
        content = intent.content

        if content.needs:
            without_skill = self._conn.execute(
                self._base_query(intent, exclude).limit(1)
            ).all()
            if without_skill:
                blocked.append("needs")

        if content.location_scope:
            stmt = self._base_query(intent, exclude)
            if content.needs:
                stmt = stmt.where(principals.c.skills.overlap(list(content.needs)))
            if self._conn.execute(stmt.limit(1)).all():
                blocked.append("location_scope")

        return blocked

    def relaxation_gain(self, intent: IntentSignal, field_name: str) -> int:
        """放宽某一项能多出多少候选。阻塞证明直接用这个数字。"""
        content = intent.content
        stmt = self._base_query(intent, frozenset())

        if field_name != "needs" and content.needs:
            stmt = stmt.where(principals.c.skills.overlap(list(content.needs)))
        if field_name != "location_scope" and content.location_scope:
            zone = _zone_of(content.location_scope)
            if zone:
                stmt = stmt.where(
                    sa.or_(principals.c.zone == zone, principals.c.zone.is_(None))
                )

        widened = self._conn.execute(
            sa.select(sa.func.count()).select_from(stmt.subquery())
        ).scalar_one()
        current = self._conn.execute(
            sa.select(sa.func.count()).select_from(
                self._hard_filter_query(intent).subquery()
            )
        ).scalar_one()
        return max(0, widened - current)

    def _hard_filter_query(self, intent: IntentSignal):  # type: ignore[no-untyped-def]
        stmt = self._base_query(intent, frozenset())
        content = intent.content
        if content.needs:
            stmt = stmt.where(principals.c.skills.overlap(list(content.needs)))
        if content.location_scope:
            zone = _zone_of(content.location_scope)
            if zone:
                stmt = stmt.where(
                    sa.or_(principals.c.zone == zone, principals.c.zone.is_(None))
                )
        return stmt

    # --- 第二段：召回 ---

    def _recall(
        self, intent: IntentSignal, pool: list[Candidate], *, keep: int = 40
    ) -> list[Candidate]:
        """从数百缩到数十。

        排序信号只有两个，都可解释：补上了几个缺口，以及时间够不够宽裕。
        **这里不做任何不可解释的打分**——真正的取舍留给求解器，
        它的每一条依据都要能写进成局证明。
        """
        needs = set(intent.content.needs)
        mine = intent_owner_availability(intent)

        def rank(candidate: Candidate) -> tuple[int, int]:
            covered = len(needs & set(candidate.skills))
            slack = contiguous_common_slots([mine, candidate.availability])
            return (-covered, -slack)

        return sorted(pool, key=rank)[:keep]


def intent_owner_availability(intent: IntentSignal) -> str:
    """发起人的空闲。取不到时按全空处理——宁可多召回，让求解器去筛。"""
    return getattr(intent, "_owner_availability", "1" * WEEK_SLOTS)


def _zone_of(location_scope: str) -> str | None:
    for zone in ("东校区", "西校区", "南校区"):
        if zone in location_scope:
            return zone
    return None
