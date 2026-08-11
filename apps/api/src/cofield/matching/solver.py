"""群体求解：从几十个候选里选出若干互不相同的候选组。

```
两万人 ──权限+硬约束(SQL)──▶ 数百 ──混合召回──▶ 数十 ──▶ 这里
```

三条设计不能动：

**硬约束是过滤器，不参与打分。** 六条硬约束全部进 CP-SAT 模型，违反即不可行。
没有任何权重能把一条冲突"软化"过去——时间凑不上就是凑不上，不能因为
技能特别合适就放行。

**时间是群体属性，不是两两属性。** 「我和他都周四有空」推不出「我们四个都有
连着两段」：两两都能对上的三个人，交集可能是空的。整组掩码按位与之后才谈得上
连续段。这是这个求解器存在的理由——退化成两两匹配就不需要它了。

**无解时不伪造候选。** 逐条卸掉约束重解，留下的那一组是不可约的真凶
（deletion filter，得到的是极小不可行子集）。用户要知道的是「卡在哪」，
不是「没找到」。

每个软目标产出一条能独立解释的贡献。解释里只许出现具体的人和具体的事实，
不出现分数与百分比——成局证明禁止黑箱分数，这里是它的上游。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from ortools.sat.python import cp_model

from cofield.matching.contracts import (
    WEEK_SLOTS,
    CandidateGroup,
    ConstraintKind,
    HardConstraint,
    Member,
    ObjectiveContribution,
    ObjectiveKind,
    Requirement,
    SolveRequest,
    SolveResult,
    SolverStatus,
)
from cofield.matching.funnel import contiguous_common_slots

#: 权重是浮点，CP-SAT 只吃整数系数——统一放大取整。
_WEIGHT_SCALE = 100

#: 求解器的最小时间片。给 0 秒等于不搜索，那是配置错误而不是意图。
_MIN_SECONDS = 0.01

#: 一周 7 天 × 3 段，位 0 是周一上午（与合成人口的掩码约定一致）。
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_PERIODS = ("上午", "下午", "晚上")

#: 诊断时的卸载顺序。先试着卸掉结构性的（人数、校区、并发、排除），
#: 让「缺人」「缺时间」这类用户真正在意的原因更可能留在最后的报告里。
_DIAGNOSIS_ORDER: tuple[ConstraintKind, ...] = (
    ConstraintKind.TEAM_SIZE,
    ConstraintKind.ZONE,
    ConstraintKind.CONCURRENCY,
    ConstraintKind.EXCLUSION,
    ConstraintKind.COMMON_TIME,
    ConstraintKind.ROLE_COVERAGE,
)


def solve(request: SolveRequest) -> SolveResult:
    """选出 `group_count` 个互不相同、且全部满足硬约束的候选组。"""
    started = time.perf_counter()
    pool = _pool(request)
    kinds = _kinds_in_play(request.requirement, pool)
    total = max(request.feasible_seconds + request.improve_seconds, _MIN_SECONDS)

    groups: list[CandidateGroup] = []
    forbidden: list[frozenset[UUID]] = []
    blocked: tuple[HardConstraint, ...] = ()
    exhausted = False
    timed_out = False
    all_proven = True

    while len(groups) < request.group_count:
        left = total - (time.perf_counter() - started)
        if left <= 0:
            timed_out = True
            break

        attempt = _solve_one(request, pool, kinds, forbidden, left)
        if attempt.picked is None:
            if attempt.infeasible:
                # 第一次就无解才值得诊断：后面的无解只说明「没有更多不同的组了」。
                if not groups:
                    blocked = _blame(request, pool, kinds, request.feasible_seconds)
                exhausted = True
            else:
                timed_out = True
            break

        all_proven = all_proven and attempt.proven
        groups.append(_assemble(request, attempt.picked))
        forbidden.append(frozenset(m.principal_id for m in attempt.picked))

    groups.sort(key=lambda g: (-g.score, sorted(str(i) for i in g.member_ids)))
    return SolveResult(
        groups=tuple(groups),
        blocked_by=blocked,
        solver_status=_status(
            groups=groups,
            wanted=request.group_count,
            blocked=blocked,
            timed_out=timed_out,
            exhausted=exhausted,
            all_proven=all_proven,
        ),
        elapsed_seconds=time.perf_counter() - started,
    )


def _status(
    *,
    groups: Sequence[CandidateGroup],
    wanted: int,
    blocked: Sequence[HardConstraint],
    timed_out: bool,
    exhausted: bool,
    all_proven: bool,
) -> SolverStatus:
    """状态要能区分「真的没有」和「没来得及找」——两者的后续动作完全不同。"""
    if not groups:
        if blocked:
            return SolverStatus.INFEASIBLE
        return SolverStatus.TIMEOUT if timed_out else SolverStatus.EXHAUSTED
    if timed_out:
        return SolverStatus.TIMEOUT
    if exhausted or len(groups) < wanted:
        return SolverStatus.EXHAUSTED
    return SolverStatus.OPTIMAL if all_proven else SolverStatus.FEASIBLE


# --- 候选池 -----------------------------------------------------------------


def _pool(request: SolveRequest) -> tuple[Member, ...]:
    """发起人不是可选项——他在每一个组里，只有其余人需要求解。"""
    seen = {request.requirement.requester.principal_id}
    out: list[Member] = []
    for member in request.candidates:
        if member.principal_id in seen:
            continue
        seen.add(member.principal_id)
        out.append(member)
    return tuple(out)


def _kinds_in_play(requirement: Requirement, pool: Sequence[Member]) -> frozenset[ConstraintKind]:
    """只有真的挡住了人的约束才进模型。

    挡不住任何人的约束永远不会是无解的原因，把它也拿去重解只是白花时间，
    还会让 `blocked_by` 里出现用户根本没设过的条件。
    """
    kinds = {ConstraintKind.TEAM_SIZE}
    if requirement.needs:
        kinds.add(ConstraintKind.ROLE_COVERAGE)
    if requirement.contiguous_run > 0:
        kinds.add(ConstraintKind.COMMON_TIME)
    if requirement.zone and any(_out_of_zone(m, requirement.zone) for m in pool):
        kinds.add(ConstraintKind.ZONE)
    if any(m.active_commitments >= requirement.max_concurrent for m in pool):
        kinds.add(ConstraintKind.CONCURRENCY)
    if any(m.principal_id in requirement.excluded for m in pool):
        kinds.add(ConstraintKind.EXCLUSION)
    return frozenset(kinds)


def _out_of_zone(member: Member, zone: str) -> bool:
    """zone 为 None 的人到哪个校区都行，不算冲突。"""
    return member.zone is not None and member.zone != zone


# --- 模型 -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ctx:
    """建模时用得到的一切。目标项要往模型里加变量，所以 model 也在这。"""

    model: cp_model.CpModel
    requirement: Requirement
    pool: tuple[Member, ...]
    take: tuple[cp_model.IntVar, ...]
    windows: tuple[cp_model.IntVar, ...]


@dataclass(frozen=True, slots=True)
class _Program:
    model: cp_model.CpModel
    take: tuple[cp_model.IntVar, ...]
    objective: cp_model.LinearExprT | None


def _program(
    request: SolveRequest,
    pool: tuple[Member, ...],
    kinds: frozenset[ConstraintKind],
    forbidden: Sequence[frozenset[UUID]],
    *,
    scored: bool,
) -> _Program:
    requirement = request.requirement
    model = cp_model.CpModel()
    take = tuple(model.new_bool_var(f"take_{i}") for i in range(len(pool)))
    run = max(1, requirement.contiguous_run)

    if ConstraintKind.TEAM_SIZE in kinds:
        # 发起人已经占掉一个位置，剩下的名额才是可选的。
        model.add(cp_model.LinearExpr.sum(take) >= max(0, requirement.team_min - 1))
        model.add(cp_model.LinearExpr.sum(take) <= max(0, requirement.team_max - 1))

    if ConstraintKind.ROLE_COVERAGE in kinds:
        for need in requirement.needs:
            if need in requirement.requester.skills:
                continue
            # 空子句即不可行：没人会这一项时，这条约束自己就把解否了。
            model.add_bool_or([take[i] for i, m in enumerate(pool) if need in m.skills])

    windows = _window_vars(model, requirement, pool, take, run)
    if ConstraintKind.COMMON_TIME in kinds:
        model.add_bool_or(list(windows))

    if ConstraintKind.ZONE in kinds and requirement.zone:
        for index, member in enumerate(pool):
            if _out_of_zone(member, requirement.zone):
                model.add(take[index] == 0)

    if ConstraintKind.CONCURRENCY in kinds:
        for index, member in enumerate(pool):
            if member.active_commitments >= requirement.max_concurrent:
                model.add(take[index] == 0)

    if ConstraintKind.EXCLUSION in kinds:
        for index, member in enumerate(pool):
            if member.principal_id in requirement.excluded:
                model.add(take[index] == 0)

    for previous in forbidden:
        # 只禁掉这一整套人选，不禁掉其中任何一个人——他可以出现在别的组里。
        model.add_bool_or(
            [
                ~take[i] if m.principal_id in previous else take[i]
                for i, m in enumerate(pool)
            ]
        )

    ctx = _Ctx(model=model, requirement=requirement, pool=pool, take=take, windows=windows)
    objective = _objective(ctx, request) if scored else None
    return _Program(model=model, take=take, objective=objective)


def _window_vars(
    model: cp_model.CpModel,
    requirement: Requirement,
    pool: Sequence[Member],
    take: Sequence[cp_model.IntVar],
    run: int,
) -> tuple[cp_model.IntVar, ...]:
    """每个「连续 run 段」起点一个布尔量：这一段整组都空得下来吗。

    这是时间约束不肯退化成两两匹配的地方——它约束的是**被选中的全体**，
    而不是任何一对人。只写单向蕴含（选中它 ⇒ 这段没空的人一个都不能进组）：
    硬约束只问「至少存在一段」，目标项在最大化下也会把能置真的都置真，
    于是它的和恰好等于真实的连续段数。
    """
    if run > WEEK_SLOTS:
        return ()
    windows: list[cp_model.IntVar] = []
    for start in range(WEEK_SLOTS - run + 1):
        if not _all_free(requirement.requester.availability, start, run):
            continue  # 发起人自己就没空，这一段无论选谁都成立不了
        window = model.new_bool_var(f"window_{start}")
        for index, member in enumerate(pool):
            if not _all_free(member.availability, start, run):
                model.add_implication(window, ~take[index])
        windows.append(window)
    return tuple(windows)


def _all_free(mask: str, start: int, run: int) -> bool:
    return all(_free(mask, start + k) for k in range(run))


def _free(mask: str, slot: int) -> bool:
    """掩码短于一周时按「没空」处理——宁可少排，不可排到人家上课的时段。"""
    return slot < len(mask) and mask[slot] == "1"


# --- 求解 -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Attempt:
    picked: tuple[Member, ...] | None
    #: 目标是否已被证明最优。改进阶段超时、返回当前最好解时为 False。
    proven: bool
    #: 可行性阶段判定的无解。区别于「没来得及找到」——后者不能用来下结论。
    infeasible: bool


def _solver(seconds: float) -> cp_model.CpSolver:
    """固定种子、单线程。

    并行搜索先撞上哪个最优解取决于线程调度：同一份输入两次求解会给出不同的
    组合。提案要能被复现、被申诉、被 A/B 对照，所以宁可慢也不要多线程。
    """
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(seconds, _MIN_SECONDS)
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    return solver


def _solve_one(
    request: SolveRequest,
    pool: tuple[Member, ...],
    kinds: frozenset[ConstraintKind],
    forbidden: Sequence[frozenset[UUID]],
    budget_left: float,
) -> _Attempt:
    """先证明有解，再谈好坏。

    两段预算不是节流技巧：可行性阶段不带目标函数，无解时它不必为「证明这个解
    最优」白花时间；有解之后再拿改进预算去挑，超时也有当前最好解可以交。
    """
    program = _program(request, pool, kinds, forbidden, scored=True)
    started = time.perf_counter()

    solver = _solver(min(request.feasible_seconds, budget_left))
    status = solver.solve(program.model)
    if status == cp_model.INFEASIBLE:
        return _Attempt(picked=None, proven=True, infeasible=True)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _Attempt(picked=None, proven=False, infeasible=False)

    for var in program.take:
        program.model.add_hint(var, solver.boolean_value(var))
    if program.objective is not None:
        program.model.maximize(program.objective)

    # 改进预算按组数均摊：第一个组不该把后面几个组的时间也花光。
    share = request.improve_seconds / max(1, request.group_count)
    left = budget_left - (time.perf_counter() - started)
    improver = _solver(min(share, max(left, _MIN_SECONDS)))
    improved = improver.solve(program.model)
    if improved in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        best, proven = improver, improved == cp_model.OPTIMAL
    else:
        best, proven = solver, False

    picked = tuple(m for m, var in zip(pool, program.take, strict=True) if best.boolean_value(var))
    return _Attempt(picked=picked, proven=proven, infeasible=False)


# --- 无解诊断 ---------------------------------------------------------------


def _blame(
    request: SolveRequest,
    pool: tuple[Member, ...],
    kinds: frozenset[ConstraintKind],
    seconds: float,
) -> tuple[HardConstraint, ...]:
    """哪几条硬约束**共同**导致了无解。

    逐条卸掉重解：卸掉之后照样无解，说明它不是原因，剔除；卸掉之后有解了，
    说明它是必需的一环，留下。剩下的这组不可再约减——每一条都必须在，
    少任何一条都能凑出队。用户据此知道放宽哪一项才有用。
    """
    keep = {kind for kind in _DIAGNOSIS_ORDER if kind in kinds}
    for kind in _DIAGNOSIS_ORDER:
        if kind not in keep:
            continue
        trial = frozenset(keep - {kind})
        if _proven_infeasible(request, pool, trial, seconds):
            keep.discard(kind)
    return tuple(
        HardConstraint(kind, _detail(kind, request, pool))
        for kind in _DIAGNOSIS_ORDER
        if kind in keep
    )


def _proven_infeasible(
    request: SolveRequest,
    pool: tuple[Member, ...],
    kinds: frozenset[ConstraintKind],
    seconds: float,
) -> bool:
    """只有求解器明确说 INFEASIBLE 才算数。

    超时（UNKNOWN）不是无解——把它当无解会剔掉真正的元凶，让用户去放宽一个
    根本不碍事的条件。
    """
    program = _program(request, pool, kinds, (), scored=False)
    return _solver(seconds).solve(program.model) == cp_model.INFEASIBLE


def _detail(kind: ConstraintKind, request: SolveRequest, pool: Sequence[Member]) -> str:
    requirement = request.requirement
    if kind is ConstraintKind.ROLE_COVERAGE:
        covered = set(requirement.requester.skills)
        for member in pool:
            covered |= member.skills
        missing = [need for need in requirement.needs if need not in covered]
        if missing:
            return f"候选里没有人会{'、'.join(missing)}"
        return f"在人数限制内凑不齐{'、'.join(requirement.needs)}"
    if kind is ConstraintKind.TEAM_SIZE:
        want = f"{requirement.team_min}–{requirement.team_max}"
        return f"可用候选 {len(pool)} 人，凑不出 {want} 人的组"
    if kind is ConstraintKind.COMMON_TIME:
        return f"整组找不到 {requirement.contiguous_run} 个连续时段的共同空闲"
    if kind is ConstraintKind.ZONE:
        return f"候选里在{requirement.zone}的人不够"
    if kind is ConstraintKind.CONCURRENCY:
        return f"能补上缺口的人已经同时参与了 {requirement.max_concurrent} 件事"
    return f"被排除的 {len(requirement.excluded)} 人正是能补上缺口的人"


# --- 组装与解释 -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scene:
    """写解释要用到的全部事实。

    解释只许引用这里的东西——每一条都能追溯回输入，才谈得上可申诉。
    """

    requirement: Requirement
    members: tuple[Member, ...]
    picked: tuple[Member, ...]
    role_assignment: dict[str, UUID]
    common_slots: tuple[int, ...]
    _names: dict[UUID, str] = field(default_factory=dict)

    def name_of(self, principal_id: UUID) -> str:
        return self._names.get(principal_id, "对方")


def _assemble(request: SolveRequest, picked: tuple[Member, ...]) -> CandidateGroup:
    requirement = request.requirement
    members = (requirement.requester, *picked)
    run = max(1, requirement.contiguous_run)
    common = _windows([m.availability for m in members], run)
    role_assignment = _assign_roles(requirement, members)

    scene = _Scene(
        requirement=requirement,
        members=members,
        picked=picked,
        role_assignment=role_assignment,
        common_slots=common,
        _names={m.principal_id: m.display_name for m in members},
    )

    contributions: list[ObjectiveContribution] = []
    for objective in request.objectives:
        aspect = _ASPECTS[objective.kind]
        raw = aspect.measure(scene)
        contributions.append(
            ObjectiveContribution(
                kind=objective.kind,
                raw=raw,
                weighted=raw * objective.weight,
                explanation=aspect.explain(scene, raw),
            )
        )

    return CandidateGroup(
        members=members,
        role_assignment=role_assignment,
        common_slots=common,
        contributions=tuple(contributions),
        score=sum(c.weighted for c in contributions),
    )


def _assign_roles(requirement: Requirement, members: Sequence[Member]) -> dict[str, UUID]:
    """每个缺口指名一个人。

    优先派组员而不是发起人：缺口的定义就是发起人一个人做不成的那部分，
    让他自己补上等于没解决。同一个人也尽量不身兼两职——一人分饰两角的组，
    那个人一退整组就塌。
    """
    requester = requirement.requester.principal_id
    assignment: dict[str, UUID] = {}
    busy: set[UUID] = set()

    for need in requirement.needs:
        able = [m for m in members if need in m.skills]
        able.sort(key=lambda m: (m.principal_id in busy, m.principal_id == requester))
        if not able:
            continue
        assignment[need] = able[0].principal_id
        busy.add(able[0].principal_id)
    return assignment


def _windows(masks: Sequence[str], run: int) -> tuple[int, ...]:
    """整组共同空闲的连续段起点。

    `funnel.contiguous_common_slots` 只给数量，而证明里要指到「周四晚上」，
    所以这里补出位置。两者说的必须是同一件事，由测试盯住。
    """
    if not masks or run <= 0 or run > WEEK_SLOTS:
        return ()
    common = [all(_free(m, i) for m in masks) for i in range(WEEK_SLOTS)]
    return tuple(
        start
        for start in range(WEEK_SLOTS - run + 1)
        if all(common[start + k] for k in range(run))
    )


def _slot_name(slot: int) -> str:
    return f"{_WEEKDAYS[(slot // 3) % 7]}{_PERIODS[slot % 3]}"


# --- 软目标：线性式、实际值、给人看的一句话 ---------------------------------


@dataclass(frozen=True, slots=True)
class _Term:
    """一个目标项的线性形式。系数已是整数，权重在汇总时才乘上去。"""

    literals: tuple[cp_model.IntVar, ...]
    coefficients: tuple[int, ...]
    constant: int = 0


@dataclass(frozen=True, slots=True)
class _Aspect:
    """一个软目标的三副面孔。

    三者说的必须是同一件事：模型在最大化的、证明里报出的、和讲给人听的
    如果不一致，那份证明就是假的。
    """

    linear: Callable[[_Ctx], _Term]
    measure: Callable[[_Scene], float]
    explain: Callable[[_Scene, float], str]


def _objective(ctx: _Ctx, request: SolveRequest) -> cp_model.LinearExprT:
    literals: list[cp_model.IntVar] = []
    coefficients: list[int] = []
    constant = 0
    for objective in request.objectives:
        term = _ASPECTS[objective.kind].linear(ctx)
        scale = round(objective.weight * _WEIGHT_SCALE)
        literals.extend(term.literals)
        coefficients.extend(c * scale for c in term.coefficients)
        constant += term.constant * scale
    return cp_model.LinearExpr.weighted_sum(literals, coefficients) + constant


def _two_way(requester: Member, other: Member) -> int:
    """互惠取双向的较小值——单向帮忙不是互惠，那是消耗。"""
    return min(len(requester.skills - other.skills), len(other.skills - requester.skills))


# ROLE_FIT：落在缺口上的技能数。重复覆盖也算，因为它意味着有人来不了还顶得住。


def _term_role_fit(ctx: _Ctx) -> _Term:
    needs = frozenset(ctx.requirement.needs)
    return _Term(
        literals=ctx.take,
        coefficients=tuple(len(needs & m.skills) for m in ctx.pool),
        constant=len(needs & ctx.requirement.requester.skills),
    )


def _measure_role_fit(scene: _Scene) -> float:
    needs = frozenset(scene.requirement.needs)
    return float(sum(len(needs & m.skills) for m in scene.members))


def _explain_role_fit(scene: _Scene, raw: float) -> str:
    if not scene.role_assignment:
        return "这次没写明缺什么，大家带来的本事都算额外的"
    filled = "，".join(
        f"{scene.name_of(pid)}补上了{need}" for need, pid in scene.role_assignment.items()
    )
    if raw > len(scene.role_assignment):
        return f"{filled}；这几项还不止一个人会，有人临时来不了也顶得住"
    return filled


# RECIPROCITY：双向都拿得出对方没有的东西。


def _term_reciprocity(ctx: _Ctx) -> _Term:
    requester = ctx.requirement.requester
    return _Term(
        literals=ctx.take,
        coefficients=tuple(_two_way(requester, m) for m in ctx.pool),
    )


def _measure_reciprocity(scene: _Scene) -> float:
    requester = scene.requirement.requester
    return float(sum(_two_way(requester, m) for m in scene.picked))


def _explain_reciprocity(scene: _Scene, raw: float) -> str:
    requester = scene.requirement.requester
    if raw <= 0:
        return "这次更像是单向帮忙——你拿得出的东西，组里暂时用不上"
    best = max(scene.picked, key=lambda m: (_two_way(requester, m), str(m.principal_id)))
    gives = sorted(requester.skills - best.skills)
    takes = sorted(best.skills - requester.skills)
    return f"你会{gives[0]}，{best.display_name}会{takes[0]}，两边都拿得出对方没有的"


# TIME_SLACK：整组还剩几个连续段可选。只有一段的组，一次改期就散了。


def _term_time_slack(ctx: _Ctx) -> _Term:
    return _Term(literals=ctx.windows, coefficients=(1,) * len(ctx.windows))


def _measure_time_slack(scene: _Scene) -> float:
    """连续段的**数量**由漏斗那支函数说了算。

    同一件事在两个地方各算一遍，迟早会算出两个数；这里只补它没给的位置。
    """
    run = max(1, scene.requirement.contiguous_run)
    return float(contiguous_common_slots([m.availability for m in scene.members], run=run))


def _explain_time_slack(scene: _Scene, raw: float) -> str:
    if not scene.common_slots:
        return "整组还没有连得上的时段"
    named = "、".join(_slot_name(s) for s in scene.common_slots[:3])
    if len(scene.common_slots) == 1:
        return f"整组只有{named}连得上，错开这一次就得重新约"
    if len(scene.common_slots) > 3:
        return f"整组在{named}这些时段都连得上，临时改期也还有余地"
    return f"整组在{named}连得上"


# CROSS_MAJOR：组里有几个不同的专业。


def _term_cross_major(ctx: _Ctx) -> _Term:
    mine = ctx.requirement.requester.major
    literals: list[cp_model.IntVar] = []
    for major in sorted({m.major for m in ctx.pool if m.major}):
        if major == mine:
            continue  # 发起人在每个组里，他的专业恒定出现，算作常数
        present = ctx.model.new_bool_var(f"major_{major}")
        # 单向即可：最大化会把能置真的都置真，于是这个和等于真实的专业数。
        ctx.model.add(
            present
            <= cp_model.LinearExpr.sum(
                [ctx.take[i] for i, m in enumerate(ctx.pool) if m.major == major]
            )
        )
        literals.append(present)
    return _Term(
        literals=tuple(literals),
        coefficients=(1,) * len(literals),
        constant=1 if mine else 0,
    )


def _measure_cross_major(scene: _Scene) -> float:
    return float(len({m.major for m in scene.members if m.major}))


def _explain_cross_major(scene: _Scene, raw: float) -> str:
    majors = sorted({m.major for m in scene.members if m.major})
    if not majors:
        return "组里没人填过专业，看不出视角是不是重叠"
    if len(majors) == 1:
        return f"组里都是{majors[0]}的人，看问题的角度会比较一致"
    return f"组里跨了{'、'.join(majors)}，不是在一个专业里打转"


# EXPOSURE_FAIRNESS：被反复推荐的人要降权，否则提案全堆到少数热门候选身上。


def _term_exposure(ctx: _Ctx) -> _Term:
    return _Term(
        literals=ctx.take,
        coefficients=tuple(m.recent_exposure for m in ctx.pool),
    )


def _measure_exposure(scene: _Scene) -> float:
    return float(sum(m.recent_exposure for m in scene.picked))


def _explain_exposure(scene: _Scene, raw: float) -> str:
    if raw <= 0 or not scene.picked:
        return "这几位最近都没有被推到别人面前，答应下来的可能更大"
    busiest = max(scene.picked, key=lambda m: (m.recent_exposure, str(m.principal_id)))
    return f"{busiest.display_name}最近被反复推荐给别人，档期可能已经排满"


# NEWCOMER_PROTECTION：零历史的人不该因为缺历史而系统性地进不了组。


def _term_newcomer(ctx: _Ctx) -> _Term:
    return _Term(
        literals=ctx.take,
        coefficients=tuple(1 if m.confirmed_events == 0 else 0 for m in ctx.pool),
    )


def _measure_newcomer(scene: _Scene) -> float:
    return float(sum(1 for m in scene.picked if m.confirmed_events == 0))


def _explain_newcomer(scene: _Scene, raw: float) -> str:
    fresh = [m.display_name for m in scene.picked if m.confirmed_events == 0]
    if not fresh:
        return "组里每个人都有过共同完成的事件，都拿得出可核验的经历"
    return f"{'、'.join(fresh)}还没有共同完成过事件，这一组给了位置"


_ASPECTS: dict[ObjectiveKind, _Aspect] = {
    ObjectiveKind.ROLE_FIT: _Aspect(_term_role_fit, _measure_role_fit, _explain_role_fit),
    ObjectiveKind.RECIPROCITY: _Aspect(
        _term_reciprocity, _measure_reciprocity, _explain_reciprocity
    ),
    ObjectiveKind.TIME_SLACK: _Aspect(_term_time_slack, _measure_time_slack, _explain_time_slack),
    ObjectiveKind.CROSS_MAJOR: _Aspect(
        _term_cross_major, _measure_cross_major, _explain_cross_major
    ),
    ObjectiveKind.EXPOSURE_FAIRNESS: _Aspect(_term_exposure, _measure_exposure, _explain_exposure),
    ObjectiveKind.NEWCOMER_PROTECTION: _Aspect(
        _term_newcomer, _measure_newcomer, _explain_newcomer
    ),
}
