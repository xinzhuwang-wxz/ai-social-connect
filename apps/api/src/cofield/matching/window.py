"""按市场单元清算，而不是意图一提交就撮合。

## 为什么等

当平台**能识别参与者何时离开市场**时，等待以增厚市场的收益很高，而且
**超过**提高撮合速度的收益；识别不了时，贪心即时撮合才接近最优
（Akbarpour–Li–Oveis Gharan, JPE 2020）。我们的意图自带截止期——
用户主动告诉了我们他什么时候退出市场——所以我们处在"能识别"的那一侧。

**但那条定理在这里只用得上一半，必须说清楚。**

它讲的是双边市场里两边都在等的情形。我们的候选来自**全校静态人口**：
八千个会写文案的人一直都在，不会因为多等六小时而变多。所以等待并不会
让候选那一侧变厚，这一点不能含糊过去。

等待在这里买到的是另一样东西：**看得见争用**。

四十一个会调色的人对上六条都缺调色的需求，逐条求解时每条都对着全校
独立解，谁先提交谁把人占走——这正是首提案偏差（微软 Magentic Marketplace
实测：响应速度相对质量的优势达 10–30 倍）在我们这里的形态。攒着一起解，
系统才第一次看见"这六个人在抢同一批人"，才谈得上分配。

实测（三千人校园，六条都缺调色的需求）：逐条求解时同一个人最多被提给
**三条**需求，批量清算把它压到上限 **两条**，被提案的不同的人从 21 增到 23。
`MAX_PROPOSALS_PER_ROUND` 是这个机制的全部，删掉它，攒着解和逐条解的
结果一模一样。

## 清算时刻是共享的

窗口边界对齐到自然时刻，**不是"你提交后 6 小时"**。

每个人各自计时的话，争用根本不会被看见——大家仍然是各自到点各自撮合，
只是每个人都多等了六小时。共同的清算时刻才是上面那个机制成立的前提，
也才能对用户说出"明早 8 点开始配队"这种他能安排的话。

## 谁不用等

**截止期落在下次清算之前的人，立刻清算。**

这条规则是推出来的，不是拍的阈值：如果你的截止期在下次清算之前，
那到清算时你已经离开市场了，等待对你**严格更差**。
这正好是上面那条理论成立的边界条件反过来用。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection

from cofield.adapters.clock import FrozenClock
from cofield.adapters.persistence.consent import EnvelopeRepository
from cofield.adapters.persistence.intents import IntentRepository
from cofield.adapters.persistence.proposals import Proposal, ProposalRepository
from cofield.adapters.persistence.schema import intent_signals, principals
from cofield.domain.model.action_kind import ActionKindRegistry
from cofield.domain.model.consent import Audience
from cofield.domain.model.intent import IntentSignal, IntentState
from cofield.matching import proof as proof_builder
from cofield.matching import stability
from cofield.matching.contracts import (
    CandidateGroup,
    Member,
    Requirement,
    SolveRequest,
)
from cofield.matching.funnel import WEEK_SLOTS, Funnel
from cofield.matching.semantic import SemanticRetriever
from cofield.matching.solver import solve

#: 窗口边界的对齐基准。取一个固定时刻而不是"服务启动时"——
#: 后者会让同一个校园在重启前后清算在不同的分钟数上。
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

#: 没挑场景的意图按这个窗口清算。不能因为"没归类"就永远不撮合。
DEFAULT_WINDOW = timedelta(hours=6)

#: 提案的有效期。过了这个点，被提案的人很可能已经答应了别的事。
PROPOSAL_TTL = timedelta(hours=48)

#: 一次清算里，同一个人最多出现在几条需求的提案里。
#:
#: 这个上限是**批量清算真正买到的东西**。逐条求解时每条都对着全校静态人口
#: 独立解，谁先提交谁把稀缺的人全占了——这正是首提案偏差（响应速度相对质量
#: 的优势达 10–30 倍）在我们这里的形态。攒着一起解才看得见争用，才谈得上分配。
#:
#: 取 2 而不是 1：一个人同时被两队看上是正常的，他自己会选；
#: 被六队同时看上就不是"受欢迎"，是系统把一个人当成了六个人的解。
MAX_PROPOSALS_PER_ROUND = 2


@dataclass(frozen=True, slots=True)
class MarketUnit:
    """一个市场单元：同一个校园里、同一类事情、共享同一批清算时刻的人。

    单元切得太细，每个池子里没几个人，等待就白等了；切得太粗，
    组队打比赛的人和周末爬山的人被塞进同一次清算，窗口长度也没法各自合适。
    按行动类别切是这两者之间唯一有依据的分法——窗口长度本来就由类别声明。
    """

    campus_id: str
    action_kind: str | None
    window: timedelta

    def previous_clearing(self, now: datetime) -> datetime:
        elapsed = now - EPOCH
        return EPOCH + self.window * (elapsed // self.window)

    def next_clearing(self, now: datetime) -> datetime:
        return self.previous_clearing(now) + self.window


@dataclass(frozen=True, slots=True)
class Gap:
    """一样本事，多少人要、多少人给得出。

    只给聚合数，不给名字——"谁在等"是别人的事，"缺什么"才是公共信息。
    """

    skill: str
    wanted: int
    offered: int

    @property
    def scarce(self) -> bool:
        return self.wanted > self.offered


@dataclass(frozen=True, slots=True)
class MarketPulse:
    """「等配队」那一屏要显示的东西。

    它存在的理由是：让等待变成一件有信息的事。光说"请稍候"，用户只会走掉；
    说"现在 12 个人缺剪辑，只有 3 个人会"，他就知道自己该改需求、
    该去拉人、还是该自己顶上。
    """

    next_clearing_at: datetime
    waiting: int
    gaps: tuple[Gap, ...]

    @property
    def scarce_skills(self) -> tuple[str, ...]:
        return tuple(g.skill for g in self.gaps if g.scarce)


@dataclass(frozen=True, slots=True)
class ClearingReport:
    """这次清算做了什么。运维看它，复盘也看它。"""

    ran_at: datetime
    units: tuple[MarketUnit, ...]
    #: 参与了这次清算的意图数。
    considered: int
    #: 产出的提案数。
    proposed: int
    #: 一个组都凑不出来的意图数。它们不是失败——阻塞证明是产品的一部分。
    blocked: int
    #: 没等窗口就被提前清算的意图数。
    early: int


class MarketBoard:
    """读侧：告诉用户下次什么时候配队、现在这个方向上供需如何。"""

    def __init__(
        self, conn: Connection, campus_id: str, registry: ActionKindRegistry
    ) -> None:
        self._conn = conn
        self._campus = campus_id
        self._registry = registry

    def unit_for(self, action_kind: str | None) -> MarketUnit:
        window = DEFAULT_WINDOW
        if action_kind is not None:
            window = self._registry.get(action_kind).matching_window
        return MarketUnit(self._campus, action_kind, window)

    def pulse(self, action_kind: str | None, *, now: datetime) -> MarketPulse:
        unit = self.unit_for(action_kind)
        rows = self._conn.execute(
            sa.select(intent_signals.c.needs, intent_signals.c.offers)
            .where(intent_signals.c.state == IntentState.ACTIVE.value)
            .where(_same_kind(action_kind))
            .where(
                sa.or_(
                    intent_signals.c.expires_at.is_(None),
                    intent_signals.c.expires_at > now,
                )
            )
        ).all()

        wanted: Counter[str] = Counter()
        offered: Counter[str] = Counter()
        for row in rows:
            wanted.update(row.needs)
            offered.update(row.offers)

        gaps = tuple(
            Gap(skill=skill, wanted=wanted[skill], offered=offered.get(skill, 0))
            # 缺口大的排前面——用户最需要知道的是"最难补的是哪一样"。
            for skill, _ in sorted(
                wanted.items(),
                key=lambda kv: (offered.get(kv[0], 0) - kv[1], kv[0]),
            )
        )

        return MarketPulse(
            next_clearing_at=unit.next_clearing(now),
            waiting=len(rows),
            gaps=gaps,
        )


class Clearing:
    """写侧：窗口到点，把攒下来的意图一起解掉。"""

    def __init__(
        self,
        conn: Connection,
        campus_id: str,
        registry: ActionKindRegistry,
        *,
        retriever: SemanticRetriever | None = None,
    ) -> None:
        self._conn = conn
        self._campus = campus_id
        self._registry = registry
        self._retriever = retriever
        self._board = MarketBoard(conn, campus_id, registry)
        # 这条路径上的时刻一律由调用方显式传入。仓储自己去读钟会让
        # SimulatedClock 推着走的清算变得不可复现，所以这里给一个
        # 定死的钟——它一次都不会被读到。
        self._intents = IntentRepository(conn, FrozenClock(EPOCH), campus_id)
        self._envelopes = EnvelopeRepository(conn, FrozenClock(EPOCH), campus_id)
        self._proposals = ProposalRepository(conn, campus_id)

    def run(self, *, now: datetime) -> ClearingReport:
        """清算所有到点的单元，外加所有等不到下次清算的人。

        重复调用是安全的：同一个边界上已经出过提案的意图会被跳过，
        因为 `cleared_at` 记的是**边界时刻**而不是"跑这一次的时刻"。
        """
        units: list[MarketUnit] = []
        considered = proposed = blocked = early = 0
        # 一轮之内共享的曝光计数。它是批量清算与逐条求解的**唯一**区别——
        # 没有它，攒着解和来一条解一条给出的结果完全一样。
        exposure: Counter[UUID] = Counter()

        kinds: list[str | None] = [k.key for k in self._registry.all()]
        kinds.append(None)

        for action_kind in kinds:
            unit = self._board.unit_for(action_kind)
            boundary = unit.previous_clearing(now)
            due, urgent = self._waiting(unit, now=now, boundary=boundary)
            if not due and not urgent:
                continue

            units.append(unit)
            early += len(urgent)
            for intent, cleared_at in [(i, boundary) for i in due] + [
                (i, now) for i in urgent
            ]:
                considered += 1
                made = self._clear_one(
                    intent, unit, cleared_at=cleared_at, now=now, exposure=exposure
                )
                proposed += made
                blocked += 0 if made else 1

        return ClearingReport(
            ran_at=now,
            units=tuple(units),
            considered=considered,
            proposed=proposed,
            blocked=blocked,
            early=early,
        )

    # --- 谁参加这次清算 ---

    def _waiting(
        self, unit: MarketUnit, *, now: datetime, boundary: datetime
    ) -> tuple[list[IntentSignal], list[IntentSignal]]:
        """分成两拨：等够了的，和等不起的。

        等够了 = 在上一个边界之前就提交了。边界之后才提交的人继续等，
        他们的等待正是让下一次市场更厚的原因。

        等不起 = 截止期落在下次清算之前。对这些人来说等待严格更差——
        到那时他们已经离开市场了。
        """
        waiting = self._intents.list_in_unit(unit.action_kind, now=now)
        next_at = unit.next_clearing(now)

        due: list[IntentSignal] = []
        urgent: list[IntentSignal] = []
        for intent in waiting:
            if self._already_proposed(intent.id, since=boundary):
                continue
            window = intent.content.time_window
            deadline = window.deadline if window else None
            if deadline is not None and deadline <= next_at:
                urgent.append(intent)
            elif intent.created_at <= boundary:
                due.append(intent)
        return due, urgent

    def _already_proposed(self, intent_id: UUID, *, since: datetime) -> bool:
        return self._proposals.exists_since(intent_id, since=since)

    # --- 解一条 ---

    def _clear_one(
        self,
        intent: IntentSignal,
        unit: MarketUnit,
        *,
        cleared_at: datetime,
        now: datetime,
        exposure: Counter[UUID],
    ) -> int:
        """回应一条需求。返回产出的提案数（0 表示凑不出来）。

        稳定性未通过的分区**不得成为提案**——这是不可越过的三条之一。
        所以过滤发生在写库之前，不是写完再标记。
        """
        shortlist = Funnel(self._conn, self._campus, retriever=self._retriever).shortlist(
            intent, now=now
        )
        if not shortlist.candidates:
            return 0

        # 这一轮已经被提够了的人不再进池。逐条求解看不见这件事，
        # 于是先提交的人会把稀缺角色全占走。
        taken = frozenset(
            pid for pid, n in exposure.items() if n >= MAX_PROPOSALS_PER_ROUND
        )
        requirement = self._requirement(intent, unit, excluded=taken)
        candidates = tuple(
            Member(
                principal_id=c.principal_id,
                display_name=c.display_name,
                skills=frozenset(c.skills),
                availability=c.availability,
                zone=c.zone,
                # 已经被别人提过的降权。硬上限之下还留一层软的，
                # 是为了让分散发生得更早，而不是等撞到墙才发生。
                recent_exposure=exposure[c.principal_id],
            )
            for c in shortlist.candidates
            if c.principal_id not in taken
        )
        if not candidates:
            return 0

        result = solve(SolveRequest(requirement=requirement, candidates=candidates))
        if not result.groups:
            return 0

        verdict = stability.check(result.groups, requirement)
        if not verdict.passed:
            # 不稳定的分区一个都不写。被塞进不喜欢的组的人会在第一次
            # 线下见面前退出，整组随之崩掉——那比"这次没配上"糟得多。
            return 0

        visible = self._visible_fields(group_members=result.groups)
        # 只给 2–3 个。实证表明选择变多反而降低决策质量：
        # 搜索上限 3→100 时福利显著下降。
        for group in result.groups[:3]:
            self._proposals.add(
                Proposal(
                    id=uuid4(),
                    intent_id=intent.id,
                    action_kind=intent.action_kind,
                    cleared_at=cleared_at,
                    member_ids=tuple(m.principal_id for m in group.members),
                    proof=proof_builder.build(
                        group,
                        requirement,
                        verdict,
                        now=now,
                        visible_fields=visible,
                    ),
                    expires_at=min(requirement.deadline, now + PROPOSAL_TTL),
                )
            )
        # 按**不同的需求**计数，不按组数：一个人出现在给同一个人的两个备选队里
        # 是正常的，那是同一次提案的两个选项；出现在六个人的提案里才是问题。
        exposure.update(
            {
                m.principal_id
                for group in result.groups[:3]
                for m in group.members
                if m.principal_id != intent.principal_id
            }
        )
        return min(len(result.groups), 3)

    def _requirement(
        self,
        intent: IntentSignal,
        unit: MarketUnit,
        *,
        excluded: frozenset[UUID] = frozenset(),
    ) -> Requirement:
        content = intent.content
        deadline = (
            content.time_window.deadline
            if content.time_window
            else unit.next_clearing(EPOCH) + timedelta(days=7)
        )
        size = content.team_size
        return Requirement(
            intent_id=intent.id,
            requester=self._requester(intent),
            goal=content.goal,
            needs=content.needs,
            team_min=size.minimum if size else 2,
            team_max=size.maximum if size else 4,
            deadline=deadline,
            zone=content.location_scope,
            excluded=excluded,
        )

    def _requester(self, intent: IntentSignal) -> Member:
        """发起人也是组员——人数、角色覆盖、共同空闲都把他算进去。

        取不到他的资料时按"全周有空、不限校区"处理：宁可让求解器多试几种，
        也不要因为资料不全就判他凑不出队。
        """
        row = self._conn.execute(
            sa.select(
                principals.c.display_name,
                principals.c.skills,
                principals.c.availability,
                principals.c.zone,
            ).where(principals.c.id == intent.principal_id)
        ).one_or_none()

        if row is None:
            return Member(
                principal_id=intent.principal_id,
                display_name="我",
                skills=frozenset(intent.content.offers),
                availability="1" * WEEK_SLOTS,
            )
        return Member(
            principal_id=intent.principal_id,
            display_name=row.display_name,
            skills=frozenset(row.skills) | frozenset(intent.content.offers),
            availability=row.availability or "1" * WEEK_SLOTS,
            zone=row.zone,
        )

    def _visible_fields(
        self, *, group_members: tuple[CandidateGroup, ...]
    ) -> frozenset[str]:
        """这次证明里可以引用**别人**的哪些属性。

        取全体组员授权的**交集**：一个人没授权，全组都降级。这是刻意的
        保守选择——多说一句别人没同意的话，比少说一句代价大得多。

        候选人多数没有为这次匹配立过授权（他们只是被搜到的，没主动发过需求），
        所以这里常常返回空集。空集下证明**仍然成立**，只是只剩求解器的结论：
        「你们凑得出连着两段都有空的时间」说得出口，「周四下午」说不出口。
        降级的是具体，不是诚实。

        逐人判断要等确认门（#9）落地——那时证明也要按人分段。
        """
        granted: frozenset[str] | None = None
        for group in group_members:
            for member in group.members:
                fields = proof_builder.attributes_visible_under(
                    self._granted_by(member.principal_id)
                )
                granted = fields if granted is None else granted & fields
        return granted or frozenset()

    def _granted_by(self, principal_id: UUID) -> frozenset[str]:
        """这个人授权给**候选人可见**的字段名。

        `SOLVER_ONLY` 那一档不算：它参与求解但不出现在任何对外输出里，
        而证明就是对外输出。把它算进来，等于把"只用于配对"这一档变成谎话。
        """
        return frozenset(
            grant.field_name
            for envelope in self._envelopes.list_active(principal_id)
            for grant in envelope.grants
            if grant.audience is Audience.CANDIDATES
        )


def _same_kind(action_kind: str | None) -> sa.ColumnElement[bool]:
    """`NULL = NULL` 在 SQL 里不成立，没挑场景的那一拨要单独判。"""
    if action_kind is None:
        return intent_signals.c.action_kind.is_(None)
    return intent_signals.c.action_kind == action_kind
