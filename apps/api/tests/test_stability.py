"""稳定性检查。

这里断言的不是「能跑」，而是**判得对**——已知存在 blocking pair 的分区必须被
拦下并精确指认到人，已知没有的必须放行，而「想走但没人要他」不算不稳定。

所有用例的偏好都是手算过的，数字写在各自的 docstring 里：权重取
`DEFAULT_OBJECTIVES`（时间 1.5、互惠 2.0、跨专业 0.8），个体的那一份按
「整组连续两段共同空闲的段数 / 队友会而他不会的技能数 / 同组不同专业的人数」算。
"""

from __future__ import annotations

import random
import re
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cofield.matching.contracts import (
    WEEK_SLOTS,
    CandidateGroup,
    Member,
    ObjectiveContribution,
    ObjectiveKind,
    Requirement,
    StabilityVerdict,
)
from cofield.matching.stability import check

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
ALL_FREE = "1" * WEEK_SLOTS


def _free_at(*slots: int) -> str:
    return "".join("1" if i in slots else "0" for i in range(WEEK_SLOTS))


def _member(
    name: str,
    skills: tuple[str, ...],
    availability: str,
    major: str | None = None,
) -> Member:
    return Member(
        principal_id=uuid4(),
        display_name=name,
        skills=frozenset(skills),
        availability=availability,
        major=major,
    )


def _group(
    members: tuple[Member, ...],
    contributions: tuple[ObjectiveContribution, ...] = (),
) -> CandidateGroup:
    return CandidateGroup(
        members=members,
        role_assignment={},
        common_slots=(),
        contributions=contributions,
        score=0.0,
    )


def _requirement(requester: Member, team_max: int = 4) -> Requirement:
    return Requirement(
        intent_id=uuid4(),
        requester=requester,
        goal="拍一支 60 秒短片",
        needs=("拍摄", "剪辑", "写文案"),
        team_min=3,
        team_max=team_max,
        deadline=NOW + timedelta(days=3),
    )


# --- 一个手算出来的 blocking pair ------------------------------------------
#
# 甲同时在两个组里（他是发起人）。乙时间全空，丙只有周一那两段加一个孤立段。
#
#   第 0 组 = 甲 + 乙 + 丙   共同空闲 = 丙的 = 连续两段只有 1 处
#   第 1 组 = 甲 + 丁 + 戊   共同空闲 = 戊的 = 连续两段有 7 处
#
# 乙在第 0 组：1×1.5 + 2×2.0 + 1×0.8 = 6.3
# 乙进第 1 组：7×1.5 + 3×2.0 + 3×0.8 = 18.9   → 他想走
# 第 1 组接不接：4 人没超上限；乙时间全空，共同空闲仍是 7；甲丁戊三人的时间不变、
#               跨专业各 +1 → 都不变差 → 接得下。所以这是真的 blocking pair。


def _unstable() -> tuple[tuple[CandidateGroup, ...], Requirement, dict[str, Member]]:
    jia = _member("甲之遥", ("写文案",), ALL_FREE, "新闻")
    yi = _member("乙川", ("拍摄",), ALL_FREE, "计算机")
    bing = _member("丙宁", ("剪辑",), _free_at(0, 1, 10), "计算机")
    ding = _member("丁禾", ("拍摄",), ALL_FREE, "美术")
    wu = _member("戊林", ("调色", "录音"), _free_at(*range(8)), "戏剧")

    groups = (_group((jia, yi, bing)), _group((jia, ding, wu)))
    people = {"甲": jia, "乙": yi, "丙": bing, "丁": ding, "戊": wu}
    return groups, _requirement(jia), people


def test_a_hand_computed_blocking_pair_is_named() -> None:
    """不通过时要指认到人和组，不能只说「不稳定」。"""
    groups, requirement, people = _unstable()

    verdict = check(groups, requirement)

    assert verdict.passed is False
    assert len(verdict.defections) == 1, "只有乙构成 blocking pair，多认或少认都是错的"
    assert verdict.defections[0].principal_id == people["乙"].principal_id
    assert verdict.defections[0].prefers_group_index == 1


def test_wanting_to_leave_is_not_enough_if_the_group_will_not_take_him() -> None:
    """丙也想去第 1 组，但他去了整组的共同空闲从 7 段掉到 1 段。

    丙进第 1 组：时间 1×1.5 + 互惠 4×2.0 + 跨专业 3×0.8 = 11.9，比他现在的 6.3 好，
    所以他确实想走。但甲会从 18.1 掉到 11.9——组里有人变差，就接不下他。
    「他想去」不等于「他走得成」，只有两者都成立才是 blocking pair。
    """
    groups, requirement, people = _unstable()

    verdict = check(groups, requirement)

    defectors = {d.principal_id for d in verdict.defections}
    assert people["丙"].principal_id not in defectors


# --- 一个手算出来的稳定分区 ------------------------------------------------
#
#   第 0 组 = 三个时间全空的人      共同空闲连续两段有 20 处
#   第 1 组 = 三个只有周一上午空的人 共同空闲连续两段有 3 处
#
# 两边都有动机被检查到：
#   · 第 1 组的人**确实想去**第 0 组（互惠 2→3、跨专业 0→3），但第 0 组的人会从
#     20 段掉到 3 段（−25.5），换来的互惠 +2、跨专业 +0.8 远远不够 → 接不下；
#   · 第 0 组的人去第 1 组会把 20 段换成 3 段 → 根本不想去。
# 所以它稳定，而且不是靠「人数满了」或「时间凑不上」这种平凡理由稳定的。


def _stable() -> tuple[tuple[CandidateGroup, ...], Requirement]:
    morning = _free_at(0, 1, 2, 3)
    jia = _member("甲之遥", ("写文案",), ALL_FREE, "新闻")
    yi = _member("乙川", ("拍摄",), ALL_FREE, "计算机")
    bing = _member("丙宁", ("剪辑",), ALL_FREE, "美术")
    ding = _member("丁禾", ("调色",), morning, "戏剧")
    wu = _member("戊林", ("录音",), morning, "戏剧")
    ji = _member("己言", ("布景",), morning, "戏剧")

    return (_group((jia, yi, bing)), _group((ding, wu, ji))), _requirement(jia)


def test_a_partition_nobody_can_improve_on_passes() -> None:
    groups, requirement = _stable()

    verdict = check(groups, requirement)

    assert verdict.passed is True
    assert verdict.defections == ()


def test_one_group_has_nowhere_to_defect_to() -> None:
    """单组必然通过——但那句话得说明它是「没有比较对象」，不是「大家都满意」。"""
    groups, requirement, _ = _unstable()

    verdict = check(groups[:1], requirement)

    assert verdict.passed is True
    assert verdict.defections == ()
    assert "没有比较对象" in verdict.statement


def test_passed_and_defections_never_disagree() -> None:
    """`passed` 与 `defections` 是同一件事的两种写法，任何输入下都不许背离。

    调用方只看 `passed` 就下了「能不能成为提案」的判断；一旦两者能不一致，
    就会出现「通过了但列着叛逃者」这种没人看得懂的证明。
    """
    unstable, requirement, _ = _unstable()
    stable, stable_requirement = _stable()

    cases: list[StabilityVerdict] = [
        check(unstable, requirement),
        check(stable, stable_requirement),
        check(unstable[:1], requirement),
        check((), requirement),
        check(tuple(reversed(unstable)), requirement),
    ]

    for verdict in cases:
        assert verdict.passed is (verdict.defections == ())


def test_the_promise_is_falsifiable() -> None:
    """通过时那句话要能被人拿去证伪：说清检查了几个组、几个人、以及检查了什么。"""
    groups, requirement = _stable()

    verdict = check(groups, requirement)

    assert verdict.statement
    assert "2 个候选组" in verdict.statement
    assert "6 个人" in verdict.statement
    assert "更想去" in verdict.statement


def test_a_defection_reason_reads_like_chinese_not_like_a_dump() -> None:
    """`reason` 是要给用户看的：有名字、有两边的具体数字、没有 UUID。"""
    groups, requirement, people = _unstable()

    reason = check(groups, requirement).defections[0].reason

    assert people["乙"].display_name in reason
    assert "第 1 组" in reason
    # 断言的是**给不给得出两边的数字**这个性质，不是那两个数。
    # 它们会随一些无关的默认值漂移（时间约束默认关掉之后就变了），
    # 而钉死具体数字只会让人在下次漂移时把断言改松，而不是想清楚。
    shift = re.search(r"从 (\d+) 段变成 (\d+) 段", reason)
    assert shift, f"没给出两边的数字，用户无从质疑：{reason}"
    assert int(shift.group(2)) > int(shift.group(1)), "说他更划算，数字却没变好"
    assert str(people["乙"].principal_id) not in reason


def test_the_solver_weights_are_read_not_reinvented() -> None:
    """同一批人，把求解器的权重全部压成 0，就不该再有人想走。

    个体偏好用的是 `contributions` 里反解出来的权重（weighted / raw），
    不是这一层自己发明的一套刻度——否则换了目标权重，稳定性判断会自说自话。
    """
    groups, requirement, _ = _unstable()
    flattened = (
        ObjectiveContribution(ObjectiveKind.TIME_SLACK, raw=7.0, weighted=0.0, explanation="压平"),
        ObjectiveContribution(ObjectiveKind.RECIPROCITY, raw=3.0, weighted=0.0, explanation="压平"),
        ObjectiveContribution(ObjectiveKind.CROSS_MAJOR, raw=2.0, weighted=0.0, explanation="压平"),
    )
    zeroed = (_group(groups[0].members, flattened), groups[1])

    assert check(groups, requirement).passed is False
    assert check(zeroed, requirement).passed is True


def test_a_full_group_cannot_take_anyone_even_if_he_wants_in() -> None:
    """人数上限是硬约束，不参与打分：满员的组再合适也接不下人。"""
    groups, requirement, _ = _unstable()
    capped = Requirement(
        intent_id=requirement.intent_id,
        requester=requirement.requester,
        goal=requirement.goal,
        needs=requirement.needs,
        team_min=requirement.team_min,
        team_max=3,
        deadline=requirement.deadline,
    )

    assert check(groups, capped).passed is True


def test_an_excluded_person_is_never_accepted_elsewhere() -> None:
    """被点名排除的人，哪个组都不能收——哪怕他在那边确实过得更好。"""
    groups, requirement, people = _unstable()
    with_exclusion = Requirement(
        intent_id=requirement.intent_id,
        requester=requirement.requester,
        goal=requirement.goal,
        needs=requirement.needs,
        team_min=requirement.team_min,
        team_max=requirement.team_max,
        deadline=requirement.deadline,
        excluded=frozenset({people["乙"].principal_id}),
    )

    assert check(groups, with_exclusion).passed is True


# --- 实测耗时 ---------------------------------------------------------------


def _crowded() -> tuple[tuple[CandidateGroup, ...], Requirement]:
    """`group_count=6`、每组 6 人的最坏情况。

    团队上限取 7 而不是 6：上限取 6 时每次接纳判定会在第一行「满员」上直接返回，
    整个组内福利循环根本不跑，测出来的数字是假的。每人只缺一个时段，保证加进第 7
    个人之后共同空闲仍然非空——否则时间那一关又会提前短路。
    """
    rng = random.Random(20260812)
    majors = ("新闻", "计算机", "美术", "戏剧", "社会学")
    skills = ("拍摄", "剪辑", "写文案", "调色", "录音", "布景")

    pool = [
        _member(
            f"候选{i:02d}",
            tuple(rng.sample(skills, 2)),
            _free_at(*(s for s in range(WEEK_SLOTS) if s != rng.randrange(WEEK_SLOTS))),
            majors[i % len(majors)],
        )
        for i in range(20)
    ]
    groups = tuple(_group(tuple(rng.sample(pool, 6))) for _ in range(6))
    return groups, _requirement(pool[0], team_max=7)


def test_six_groups_of_six_stay_well_under_the_one_second_guardrail() -> None:
    """容量护栏里那个 1 秒是估计值，这里给的是实测值。

    最坏情况的规模是 36 个成员位 × 5 个备选组 × 每次 6 个在座成员的福利复算，
    全是 21 位掩码上的按位与——量级在毫秒，离 1 秒有三个数量级的余量。
    """
    groups, requirement = _crowded()
    check(groups, requirement)  # 预热，别把首次导入算进去

    rounds = 20
    started = time.perf_counter()
    for _ in range(rounds):
        check(groups, requirement)
    each = (time.perf_counter() - started) / rounds

    assert each < 0.05, f"单次 {each * 1000:.1f} ms，已经逼近护栏，需要降级方案"


def test_the_verdict_does_not_depend_on_the_order_groups_arrive_in() -> None:
    """求解器给组的顺序不该改变「稳不稳定」这个判断，只能改变组的编号。"""
    groups, requirement, people = _unstable()

    forward = check(groups, requirement)
    backward = check(tuple(reversed(groups)), requirement)

    assert forward.passed is False
    assert backward.passed is False
    assert {d.principal_id for d in forward.defections} == {people["乙"].principal_id}
    assert {d.principal_id for d in backward.defections} == {people["乙"].principal_id}
    assert backward.defections[0].prefers_group_index == 0


def test_every_defector_points_at_a_group_he_is_not_already_in() -> None:
    """指认一个他本来就在的组是没有意义的——那不叫叛逃。"""
    groups, requirement, _ = _unstable()

    verdict = check(groups, requirement)

    for defection in verdict.defections:
        target: frozenset[UUID] = groups[defection.prefers_group_index].member_ids
        assert defection.principal_id not in target
