"""群体求解器。

跑真 CP-SAT，不替换任何一层。这里断言的不是「能解」，而是**解得对**——
硬约束真的硬、时间真的是群体属性、无解时指认的是真凶、解释真的能给人看。

最要紧的是 `test_pairwise_time_never_implies_group_time`：两两都能对上的
三个人可能凑不出一段共同空闲。这条不成立的话，这个求解器就该被两两匹配替掉。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cofield.matching.contracts import (
    DEFAULT_OBJECTIVES,
    WEEK_SLOTS,
    ConstraintKind,
    Member,
    Requirement,
    SolveRequest,
    SolveResult,
    SolverStatus,
)
from cofield.matching.funnel import contiguous_common_slots
from cofield.matching.solver import _solver, solve

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
FREE = "1" * WEEK_SLOTS

_SURNAMES = "周林沈陈许何吕施张孔曹严华金魏陶姜赵钱孙李吴郑王冯褚卫蒋秦尤袁柳崔"
_GIVEN = "雨岸知屿禾昀笙桐"
_SKILLS = ("拍摄", "剪辑", "写文案", "海报设计", "数据分析", "主持")
_MAJORS = ("新闻传播", "计算机", "设计", "工商管理", "外国语")
_ZONES = ("东校区", "南校区", None)


def _name(index: int) -> str:
    """姓名里不许出现数字——解释文案会引用它，而解释里不能有数字。"""
    return f"{_SURNAMES[index % len(_SURNAMES)]}{_GIVEN[index // len(_SURNAMES)]}"


def _mask(*slots: int) -> str:
    """只在列出的时段有空。"""
    return "".join("1" if i in slots else "0" for i in range(WEEK_SLOTS))


def _member(
    name: str,
    skills: tuple[str, ...] = (),
    availability: str = FREE,
    **rest: object,
) -> Member:
    return Member(
        principal_id=uuid4(),
        display_name=name,
        skills=frozenset(skills),
        availability=availability,
        **rest,  # type: ignore[arg-type]
    )


def _requirement(
    needs: tuple[str, ...] = ("拍摄", "剪辑"),
    *,
    requester: Member | None = None,
    team_min: int = 3,
    team_max: int = 4,
    **rest: object,
) -> Requirement:
    return Requirement(
        intent_id=uuid4(),
        requester=requester or _member("林知遥", ("写脚本",), major="新闻传播"),
        goal="拍一支 60 秒校园短片",
        needs=needs,
        team_min=team_min,
        team_max=team_max,
        deadline=NOW + timedelta(days=3),
        **rest,  # type: ignore[arg-type]
    )


def _campus(count: int = 40, seed: int = 20260812) -> tuple[Member, ...]:
    """一小片候选，各维度刻意不整齐。

    全都一样的池子测不出目标项有没有在起作用，时间也永远不会咬人。
    """
    rng = random.Random(seed)
    people: list[Member] = []
    for index in range(count):
        skills = tuple(s for s in _SKILLS if rng.random() < 0.35) or ("写文案",)
        availability = "".join("1" if rng.random() < 0.7 else "0" for _ in range(WEEK_SLOTS))
        people.append(
            _member(
                _name(index),
                skills,
                availability,
                zone=_ZONES[index % len(_ZONES)],
                major=_MAJORS[index % len(_MAJORS)],
                confirmed_events=index % 4,
                active_commitments=index % 3,
                recent_exposure=index % 5,
            )
        )
    return tuple(people)


def _kinds(result: SolveResult) -> set[ConstraintKind]:
    return {constraint.kind for constraint in result.blocked_by}


def _fingerprint(result: SolveResult) -> object:
    return tuple(
        (
            tuple(m.principal_id for m in group.members),
            tuple(sorted(group.role_assignment.items(), key=lambda kv: kv[0])),
            group.common_slots,
            round(group.score, 9),
            tuple((c.kind, c.raw, c.explanation) for c in group.contributions),
        )
        for group in result.groups
    )


# --- 能不能解 ---------------------------------------------------------------


def test_it_finds_a_group_that_covers_every_gap() -> None:
    requirement = _requirement()
    result = solve(
        SolveRequest(requirement=requirement, candidates=_campus(), group_count=3)
    )

    assert len(result.groups) == 3
    for group in result.groups:
        assert requirement.team_min <= len(group.members) <= requirement.team_max
        assert group.members[0].principal_id == requirement.requester.principal_id
        skills = set[str]().union(*(m.skills for m in group.members))
        assert set(requirement.needs) <= skills


# --- 硬约束真的是硬的 -------------------------------------------------------


def test_perfect_skills_cannot_buy_a_time_conflict() -> None:
    """技能挑不出毛病，但整组永远凑不出连续两段。

    结论必须是无解，而不是「分低但还是给你三组」——软分抵不掉一条硬冲突。
    """
    every_other = _mask(*range(0, WEEK_SLOTS, 2))  # 单段有空，但永远连不成两段
    pool = tuple(_member(_name(i), ("拍摄", "剪辑"), every_other) for i in range(8))

    result = solve(SolveRequest(requirement=_requirement(), candidates=pool, group_count=3))

    assert result.groups == ()
    assert result.solver_status is SolverStatus.INFEASIBLE
    assert ConstraintKind.COMMON_TIME in _kinds(result)


def test_pairwise_time_never_implies_group_time() -> None:
    """两两都能对上，三个人就对不上——这是这个求解器存在的理由。

    发起人整周有空，所以每组的共同空闲就是被选中那几位的交集：
    周雨和林岸在周一，周雨和沈知在周二，林岸和沈知在周三，三个人交集为空。
    退化成两两匹配的实现会在这里给出一个根本约不到一起的四人组。
    """
    both = ("拍摄", "剪辑")
    zhou = _member("周雨", both, _mask(0, 1, 3, 4))
    lin = _member("林岸", both, _mask(0, 1, 6, 7))
    shen = _member("沈知", both, _mask(3, 4, 6, 7))
    pool = (zhou, lin, shen)

    trio = solve(
        SolveRequest(
            requirement=_requirement(team_min=3, team_max=3), candidates=pool, group_count=1
        )
    )
    quartet = solve(
        SolveRequest(
            requirement=_requirement(team_min=4, team_max=4), candidates=pool, group_count=1
        )
    )

    assert trio.groups, "发起人加两个人是能凑出连续两段的"
    assert contiguous_common_slots([m.availability for m in trio.groups[0].members]) > 0

    assert quartet.groups == (), "三个人加发起人凑不出，不许因为两两都合适就放行"
    assert ConstraintKind.COMMON_TIME in _kinds(quartet)


def test_someone_at_their_concurrency_limit_is_never_pulled_in() -> None:
    """他补得上那个缺口，但他手上已经同时有三件事了。"""
    busy = _member("崔笙", ("拍摄", "调色"), active_commitments=3)
    others = tuple(_member(_name(i), ("拍摄", "剪辑")) for i in range(6))

    blocked = solve(
        SolveRequest(
            requirement=_requirement(("拍摄", "调色"), max_concurrent=3),
            candidates=(busy, *others),
            group_count=1,
        )
    )
    relaxed = solve(
        SolveRequest(
            requirement=_requirement(("拍摄",), max_concurrent=3),
            candidates=(busy, *others),
            group_count=3,
        )
    )

    assert blocked.groups == ()
    assert ConstraintKind.CONCURRENCY in _kinds(blocked)
    assert relaxed.groups
    for group in relaxed.groups:
        assert busy.principal_id not in group.member_ids


def test_a_zoned_requirement_does_not_drag_people_across_campus() -> None:
    """指定了校区就不该把东校区的人塞进来；没填校区的人到哪都行。"""
    result = solve(
        SolveRequest(
            requirement=_requirement(zone="南校区"), candidates=_campus(), group_count=3
        )
    )

    assert result.groups
    for group in result.groups:
        for member in group.members[1:]:
            assert member.zone in (None, "南校区")


# --- 无解时指认真凶 ---------------------------------------------------------


def test_a_missing_scarce_role_is_the_only_thing_it_blames() -> None:
    """只缺一个稀缺角色时，报告里只能有这一条。

    把人数、时间这些没碍事的约束也算进去，用户就会跑去放宽一个放宽了也没用的
    条件——那比只说「没找到」更糟。
    """
    pool = tuple(_member(_name(i), ("拍摄", "写文案")) for i in range(8))

    result = solve(
        SolveRequest(requirement=_requirement(("拍摄", "调色")), candidates=pool, group_count=3)
    )

    assert result.groups == ()
    assert _kinds(result) == {ConstraintKind.ROLE_COVERAGE}
    assert "调色" in result.blocked_by[0].detail


def test_blocking_the_only_one_who_could_help_names_both_reasons() -> None:
    """真凶是「排除」和「缺角色」合谋：单看任何一条都还有解。

    只放宽其中一条就能凑出队，所以两条都得说——这正是「共同导致无解」的意思。
    """
    only = _member("袁禾", ("调色", "拍摄"))
    others = tuple(_member(_name(i), ("拍摄", "剪辑")) for i in range(6))

    result = solve(
        SolveRequest(
            requirement=_requirement(("拍摄", "调色"), excluded=frozenset({only.principal_id})),
            candidates=(only, *others),
            group_count=1,
        )
    )

    assert result.groups == ()
    assert _kinds(result) == {ConstraintKind.EXCLUSION, ConstraintKind.ROLE_COVERAGE}


def test_an_empty_pool_gets_no_invented_group() -> None:
    result = solve(SolveRequest(requirement=_requirement(()), candidates=(), group_count=3))

    assert result.groups == ()
    assert result.solver_status is SolverStatus.INFEASIBLE
    assert _kinds(result) == {ConstraintKind.TEAM_SIZE}


# --- 产出是否说得清 ---------------------------------------------------------


def test_every_gap_is_named_with_who_fills_it() -> None:
    """「为什么是这几个人」直接读这张表，所以每个缺口都得有人认领。"""
    requirement = _requirement(("拍摄", "剪辑", "海报设计"), team_min=4, team_max=5)
    result = solve(
        SolveRequest(requirement=requirement, candidates=_campus(), group_count=3)
    )

    assert result.groups
    for group in result.groups:
        assert set(group.role_assignment) == set(requirement.needs)
        by_id: dict[UUID, Member] = {m.principal_id: m for m in group.members}
        for need, principal_id in group.role_assignment.items():
            assert principal_id in by_id, "认领的人必须真在这个组里"
            assert need in by_id[principal_id].skills


def test_the_slots_it_reports_are_really_common_to_everyone() -> None:
    """报出来的时段要经得起复核：整组按位与之后确实连得上。"""
    requirement = _requirement()
    result = solve(
        SolveRequest(requirement=requirement, candidates=_campus(), group_count=3)
    )

    assert result.groups
    for group in result.groups:
        masks = [m.availability for m in group.members]
        run = requirement.contiguous_run

        assert group.common_slots, "硬约束要求至少一段，报不出来就是没满足"
        assert len(group.common_slots) == contiguous_common_slots(masks, run=run)
        for start in group.common_slots:
            assert all(mask[start + k] == "1" for mask in masks for k in range(run))


def test_explanations_are_written_for_the_person_not_the_solver() -> None:
    """每一项软目标都要能单独讲给人听，且不许透出分数。

    成局证明里禁止出现总分与百分比；解释是它的上游，在这里就得干净。
    """
    result = solve(
        SolveRequest(requirement=_requirement(), candidates=_campus(), group_count=3)
    )

    assert result.groups
    for group in result.groups:
        assert {c.kind for c in group.contributions} == {o.kind for o in DEFAULT_OBJECTIVES}
        for contribution in group.contributions:
            text = contribution.explanation
            assert text, f"{contribution.kind} 没有解释"
            assert not any(ch.isdigit() for ch in text), text
            assert "%" not in text and "百分" not in text, text
            assert "匹配度" not in text and "分数" not in text and "得分" not in text, text


# --- 可复现与互不相同 -------------------------------------------------------


def test_the_groups_it_offers_are_really_different() -> None:
    result = solve(
        SolveRequest(requirement=_requirement(), candidates=_campus(), group_count=6)
    )

    assert len(result.groups) == 6
    assert len({group.member_ids for group in result.groups}) == 6


def test_same_input_gives_the_same_proposal() -> None:
    """同一份输入两次求解必须一字不差。

    提案要能被复现、被申诉、被 A/B 对照——今天推给你的组和明天推给你的组
    如果不一样，前一次的解释就无从核对。
    """
    request = SolveRequest(
        requirement=_requirement(), candidates=_campus(), group_count=4
    )

    assert _fingerprint(solve(request)) == _fingerprint(solve(request))
    assert _fingerprint(solve(request)) == _fingerprint(solve(request))


def test_parallel_search_is_off_because_it_is_not_reproducible() -> None:
    """直接盯住求解参数。

    多线程时先撞上哪个最优解取决于线程调度：同输入同输出的用例在小规模上
    可能靠运气通过，参数一旦被人打开就再也复现不了，所以盯参数本身。
    """
    parameters = _solver(1.0).parameters

    assert parameters.num_workers == 1
    assert parameters.random_seed == 0


# --- 预算 -------------------------------------------------------------------


def test_forty_candidates_and_six_groups_stay_inside_the_budget() -> None:
    """四十个候选、六个组，必须在给定的两段预算之内交货。"""
    request = SolveRequest(
        requirement=_requirement(), candidates=_campus(40), group_count=6
    )

    result = solve(request)

    assert len(result.groups) == 6
    assert result.solver_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert 0 < result.elapsed_seconds < request.feasible_seconds + request.improve_seconds
