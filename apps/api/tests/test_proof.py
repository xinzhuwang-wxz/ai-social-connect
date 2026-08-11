"""成局证明：能不能被逐条追溯，以及有没有把不该说的说出去。

这里断言的不是"能生成一段解释"，而是**这段解释经得起查**——
每条理由指向输入里真实存在的东西，没获准露出的字段一个字都不出现，
求解器和治理层的措辞不上屏幕，留给人的判断一次都不许为空。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from cofield.domain.model.consent import DELIBERATELY_UNGRANTABLE
from cofield.matching.contracts import (
    CandidateGroup,
    Defection,
    EvidenceSource,
    FormationProof,
    Member,
    Objective,
    ObjectiveContribution,
    ObjectiveKind,
    ProofLine,
    Requirement,
    StabilityVerdict,
)
from cofield.matching.proof import (
    PROOF_TTL,
    UNGRANTABLE,
    attributes_visible_under,
    build,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
FREE = "1" * 21

#: 三个人都获准露出的属性名。真实调用里由 `attributes_visible_under`
#: 从匹配信封翻译而来。
ALL_VISIBLE = frozenset(
    {"skills", "availability", "zone", "major", "confirmed_events", "active_commitments"}
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 词根黑名单。完整术语从 CONTEXT.md 读（见 `_domain_terms`），
#: 这里补的是那份表里拆不出来的部分：07 §2 映射表左列的工程词，
#: 以及任何形式的总分。
STEMS = (
    "意图",
    "主体",
    "切面",
    "共域",
    "漏斗",
    "求解",
    "约束",
    "目标项",
    "提案",
    "证明",
    "授权",
    "撮合",
    "稳定",
    "代理",
    "智能体",
    "凭证",
    "信封",
    "回声",
    "素材",
    "曝光公平",
    "policy_epoch",
    "TTL",
)
SCORES = ("%", "百分比", "匹配度", "推荐指数", "评分", "得分", "分数", "契合度")


def _domain_terms() -> frozenset[str]:
    """黑名单直接从 CONTEXT.md 的术语表生成——07 §2.1 就是这么要求的。

    手抄一份清单会跟着文档漂移。读原文的代价是路径写错时测试会静默通过，
    所以下面那条数量断言不是保险，是这个做法能成立的前提。
    """
    text = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    terms = frozenset(re.findall(r"^\*\*([^*（]+)（", text, flags=re.MULTILINE))
    assert len(terms) > 20, "没读到术语表，黑名单是空的"
    return terms


# --- 造一次成局 -------------------------------------------------------------


def _member(
    name: str,
    skills: set[str],
    *,
    zone: str | None = "南校区",
    major: str | None = None,
    confirmed: int = 2,
    commitments: int = 0,
) -> Member:
    return Member(
        principal_id=uuid4(),
        display_name=name,
        skills=frozenset(skills),
        availability=FREE,
        zone=zone,
        major=major,
        confirmed_events=confirmed,
        active_commitments=commitments,
    )


def _people() -> tuple[Member, Member, Member]:
    """发起人 + 两个补缺口的人。陈牧一件事都没做完过，用来测不确定性。"""
    return (
        _member("你", {"写脚本"}, major="新闻学", confirmed=1),
        _member("周雨", {"剪辑"}, major="视觉传达", confirmed=3),
        _member("陈牧", {"拍摄"}, major="临床医学", confirmed=0),
    )


CONTRIBUTIONS = (
    # 故意写成工程语言：这些原话一个字都不该出现在给人看的句子里。
    ObjectiveContribution(
        ObjectiveKind.ROLE_FIT, 2.0, 6.0, "硬约束满足后，切面覆盖度 0.87"
    ),
    ObjectiveContribution(ObjectiveKind.RECIPROCITY, 1.0, 2.0, "互惠项求解得分 1.0"),
    ObjectiveContribution(ObjectiveKind.TIME_SLACK, 3.0, 4.5, "共同空闲窗口 3 段"),
    ObjectiveContribution(ObjectiveKind.CROSS_MAJOR, 1.0, 0.8, "跨专业分布熵 1.0"),
)


def _case(
    *,
    people: tuple[Member, ...] | None = None,
    needs: tuple[str, ...] = ("拍摄", "剪辑"),
    zone: str | None = "南校区",
    excluded: frozenset[UUID] = frozenset(),
    deadline: datetime | None = None,
    common_slots: tuple[int, ...] = (9, 15),
    assignment: dict[str, UUID] | None = None,
    contributions: tuple[ObjectiveContribution, ...] = CONTRIBUTIONS,
    passed: bool = True,
    defections: tuple[Defection, ...] = (),
    team_min: int = 3,
    team_max: int = 4,
    max_concurrent: int = 3,
) -> tuple[CandidateGroup, Requirement, StabilityVerdict]:
    members = people or _people()
    requirement = Requirement(
        intent_id=uuid4(),
        requester=members[0],
        goal="拍一支 60 秒短片",
        needs=needs,
        team_min=team_min,
        team_max=team_max,
        deadline=deadline or NOW + timedelta(days=10),
        zone=zone,
        excluded=excluded,
        max_concurrent=max_concurrent,
    )
    if assignment is None:
        # 谁补哪个缺口按会什么来分，别按位置分——按位置分会让"周雨补上了拍摄"
        # 这种测试断言看起来对，实际上什么都没测到。
        assignment = {
            need: next(m.principal_id for m in members[1:] if need in m.skills)
            for need in needs
            if any(need in m.skills for m in members[1:])
        }
    group = CandidateGroup(
        members=members,
        role_assignment=assignment,
        common_slots=common_slots,
        contributions=contributions,
        score=17.3,
    )
    verdict = StabilityVerdict(
        passed=passed,
        defections=defections,
        statement="在当前候选池中不存在阻塞联盟（hedonic core 近似检查通过）",
    )
    return group, requirement, verdict


def _lines(proof: FormationProof) -> tuple[ProofLine, ...]:
    return (*proof.satisfied, *proof.for_humans, *proof.uncertainties)


def _texts(proof: FormationProof) -> str:
    return "\n".join(line.text for line in _lines(proof))


def _known_tokens(group: CandidateGroup, requirement: Requirement) -> set[str]:
    """输入里真实存在的可追溯对象。`refers_to` 只许指向这些。"""
    tokens = {f"principal:{m.principal_id}" for m in group.members}
    tokens |= {f"need:{n}" for n in requirement.needs}
    tokens |= {f"need:{n}" for n in group.role_assignment}
    tokens |= {f"slot:{s}" for s in group.common_slots}
    tokens |= {f"objective:{c.kind.value}" for c in group.contributions}
    tokens.add(f"intent:{requirement.intent_id}")
    if requirement.zone:
        tokens.add(f"zone:{requirement.zone}")
    return tokens


# --- 不许有总分，不许有术语 -------------------------------------------------


def test_no_score_no_percentage_no_domain_vocabulary() -> None:
    """屏幕上的每一句都要过这一关。

    「匹配度 87%」是这个产品从第一天起就不做的东西；领域词汇泄漏则是
    07 说的最大落地风险——两者都可被机器检查，就不该靠 review 凭感觉抓。
    """
    group, requirement, verdict = _case()
    proof = build(
        group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE
    )

    banned = (*_domain_terms(), *STEMS, *SCORES)
    for line in _lines(proof):
        for word in banned:
            assert word not in line.text, f"{word!r} 出现在了给人看的句子里：{line.text}"
    assert "17.3" not in _texts(proof), "总分泄漏到了界面上"


def test_the_solver_wording_stays_off_the_page_but_not_out_of_the_record() -> None:
    """求解器写的解释是工程语言，原样搬上屏幕就是术语泄漏。

    但也不能丢：申诉时要能看到系统当时到底按什么算的，所以它进 notes。
    """
    group, requirement, verdict = _case()
    proof = build(
        group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE
    )

    page = _texts(proof)
    for contribution in CONTRIBUTIONS:
        assert contribution.explanation not in page
        assert any(contribution.explanation in note for note in proof.notes)
    assert verdict.statement not in page
    assert any(verdict.statement in note for note in proof.notes)


# --- 没获准露出的，一个字都不许出现 -----------------------------------------


def test_an_unauthorized_field_never_reaches_the_page() -> None:
    """专业没被授权露出时，任何人的专业都不许出现在证明里。

    先证明这条守卫是活的：全部获准时专业确实写得出来。否则这个用例
    可能只是因为代码根本没写那一行而通过。
    """
    group, requirement, verdict = _case()

    shown = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)
    assert "视觉传达" in _texts(shown), "全部获准时都写不出专业，这条守卫测不到东西"

    hidden = build(
        group,
        requirement,
        verdict,
        now=NOW,
        visible_fields=ALL_VISIBLE - {"major"},
    )
    page = _texts(hidden)
    for member in group.members:
        assert member.major
        assert member.major not in page, f"{member.display_name}的专业漏出去了"


def test_a_calendar_that_was_not_shared_keeps_the_conclusion_and_drops_the_days() -> (
    None
):
    """「时间凑得上」是求解器的结论，「周四下午」是别人日程里的内容。

    没获准露出日程时降级的是具体，不是诚实——那条硬约束确实被满足了，
    这句话仍然要说得出口。
    """
    group, requirement, verdict = _case()
    proof = build(
        group,
        requirement,
        verdict,
        now=NOW,
        visible_fields=ALL_VISIBLE - {"availability"},
    )

    page = _texts(proof)
    for day in ("周一", "周二", "周三", "周四", "周五", "周六", "周日"):
        assert day not in page
    assert not any(
        token.startswith("slot:") for line in _lines(proof) for token in line.refers_to
    )
    assert any("有空的时间" in line.text for line in proof.satisfied)


def test_who_fills_which_gap_needs_permission_but_the_coverage_does_not() -> None:
    """不能说「周雨会剪辑」的时候，仍然要说「剪辑有人补上了」。"""
    group, requirement, verdict = _case()

    named = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)
    assert "周雨补上了缺的剪辑。" in _texts(named)

    anonymous = build(
        group,
        requirement,
        verdict,
        now=NOW,
        visible_fields=ALL_VISIBLE - {"skills"},
    )
    page = _texts(anonymous)
    assert "周雨补上了" not in page
    assert "缺的拍摄、剪辑都有人补上了。" in page


def test_nothing_is_dropped_silently() -> None:
    """略去的东西要留痕。悄悄少一条比说不出口更糟。"""
    group, requirement, verdict = _case()
    proof = build(group, requirement, verdict, now=NOW, visible_fields=frozenset())

    assert any("未获准露出" in note for note in proof.notes)
    assert any("major" in note for note in proof.notes)


# --- 每条都要指得着 ---------------------------------------------------------


def test_every_citation_points_at_something_that_really_exists() -> None:
    group, requirement, verdict = _case(
        excluded=frozenset(), passed=False, defections=()
    )
    known = _known_tokens(group, requirement)
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    cited = 0
    for line in _lines(proof):
        for token in line.refers_to:
            assert token in known, f"{token} 指向输入里不存在的东西：{line.text}"
            cited += 1
    assert cited > 0
    assert all(line.refers_to for line in proof.satisfied), "已满足的每条都要指得着"


def test_only_the_five_allowed_sources_are_used() -> None:
    """五种来源之外不许有第六种，而且不能只用其中一种糊过去。"""
    group, requirement, verdict = _case(passed=False, defections=())
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    used = {line.source for line in _lines(proof)}
    assert used <= set(EvidenceSource)
    assert len(used) >= 4, "来源过于单一，说明有条目被塞进了不属于它的那一类"


# --- 稳定性 -----------------------------------------------------------------


def test_a_failed_stability_check_is_carried_not_swallowed() -> None:
    """没通过的分区不得成为提案，但那是调用方的决定。

    这一层的职责是**如实带上**——把结论吞掉，调用方就无从拒绝。
    """
    group, requirement, _ = _case()
    unstable = StabilityVerdict(
        passed=False,
        defections=(
            Defection(
                principal_id=group.members[1].principal_id,
                prefers_group_index=2,
                reason="组 2 的时间更宽裕",
            ),
        ),
        statement="存在阻塞联盟",
    )
    proof = build(group, requirement, unstable, now=NOW, visible_fields=ALL_VISIBLE)

    assert proof.stability is unstable
    assert proof.stability.passed is False
    assert "都没有更想去的组" not in _texts(proof), "没通过却说了那句通过时的话"
    assert any(
        line.source is EvidenceSource.UNRESOLVED_CONFLICT and "周雨" in line.text
        for line in proof.uncertainties
    )
    assert "组 2 的时间更宽裕" not in _texts(proof), "求解器的措辞漏到了界面上"


def test_a_passing_check_makes_the_one_promise_that_can_be_falsified() -> None:
    group, requirement, verdict = _case()
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    assert any("这几个人现在都没有更想去的组。" == line.text for line in proof.satisfied)


# --- 冲突与不确定 -----------------------------------------------------------


def test_an_excluded_person_in_the_group_is_admitted_as_a_conflict() -> None:
    """用户说过不想和谁一起，这个人却还在组里——这是冲突，不是细节。"""
    members = _people()
    group, requirement, verdict = _case(
        people=members, excluded=frozenset({members[2].principal_id})
    )
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    conflicts = [
        line
        for line in proof.uncertainties
        if line.source is EvidenceSource.UNRESOLVED_CONFLICT
    ]
    assert any("陈牧" in line.text for line in conflicts)


def test_a_gap_nobody_took_is_never_reported_as_satisfied() -> None:
    members = _people()
    group, requirement, verdict = _case(
        people=members,
        assignment={"拍摄": members[2].principal_id},
    )
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    assert not any("缺的剪辑" in line.text for line in proof.satisfied)
    assert any("剪辑" in line.text and "还没人认领" in line.text for line in proof.uncertainties)


def test_a_shrinking_window_is_admitted_out_loud() -> None:
    """时间窗只剩两天是系统知道、用户未必知道的事。藏起来伤害更大。"""
    group, requirement, verdict = _case(deadline=NOW + timedelta(hours=20))
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    assert any("不到一天" in line.text for line in proof.uncertainties)


def test_an_unverified_skill_is_admitted_when_the_history_was_shared() -> None:
    """陈牧一件事都没做完过——他的拍摄目前只是他自己写的。"""
    group, requirement, verdict = _case()
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    assert any(
        "陈牧" in line.text and "验证过" in line.text for line in proof.uncertainties
    )


def test_an_overloaded_member_is_named_only_if_that_was_shared() -> None:
    busy = _people()
    busy = (busy[0], busy[1], _member("陈牧", {"拍摄"}, confirmed=0, commitments=3))
    group, requirement, verdict = _case(people=busy, max_concurrent=3)

    shown = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)
    assert any("陈牧" in line.text and "排满" in line.text for line in shown.uncertainties)

    hidden = build(
        group,
        requirement,
        verdict,
        now=NOW,
        visible_fields=ALL_VISIBLE - {"active_commitments"},
    )
    assert any("有人" in line.text and "排满" in line.text for line in hidden.uncertainties)
    assert not any(
        "陈牧" in line.text and "排满" in line.text for line in hidden.uncertainties
    )


# --- 留给人的 ---------------------------------------------------------------


def test_there_is_always_something_left_for_a_person_to_decide() -> None:
    """任何一次成局都必然有留给人的判断。空的就是错的。"""
    cases = (
        _case(),
        _case(passed=False),
        _case(zone=None, contributions=()),
        _case(common_slots=(), needs=()),
    )
    for group, requirement, verdict in cases:
        for visible in (ALL_VISIBLE, frozenset()):
            proof = build(
                group, requirement, verdict, now=NOW, visible_fields=visible
            )
            assert proof.for_humans, "留给人的判断为空"


def test_what_is_left_for_humans_is_judgment_not_missing_data() -> None:
    """留给人的不是系统算不出来的，是系统**不该**替人算的。"""
    group, requirement, verdict = _case()
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    page = "\n".join(line.text for line in proof.for_humans)
    assert "合不合得来" in page
    assert "署名" in page
    assert "不等于那天真能来" in page


# --- 有效期 -----------------------------------------------------------------


def test_a_proof_expires_before_the_people_in_it_move_on() -> None:
    """两个上界取较早：截止之后没有意义，72 小时之后引用的内容已经失效。"""
    far, requirement_far, verdict = _case(deadline=NOW + timedelta(days=10))
    proof = build(far, requirement_far, verdict, now=NOW, visible_fields=ALL_VISIBLE)
    assert proof.expires_at == NOW + PROOF_TTL

    near, requirement_near, verdict = _case(deadline=NOW + timedelta(hours=5))
    proof = build(near, requirement_near, verdict, now=NOW, visible_fields=ALL_VISIBLE)
    assert proof.expires_at == NOW + timedelta(hours=5)
    assert proof.generated_at == NOW


# --- 与授权白名单的接缝 -----------------------------------------------------


def test_the_two_vocabularies_have_exactly_one_translation() -> None:
    """信封说 offers，证明问「能不能说他会剪辑」——两套词表必须有一处翻译。

    只有一处：两边各自拼字符串迟早对不上。
    """
    assert attributes_visible_under(frozenset({"offers", "time_window"})) == frozenset(
        {"skills", "availability"}
    )
    assert attributes_visible_under(frozenset()) == frozenset()


def test_how_busy_someone_is_can_never_be_said_out_loud() -> None:
    """`active_commitments` 参与求解，但永远进不了证明。

    「他手上已经有三件事」会被读成一个负面判断，而且没有人会主动选择
    公布自己有多忙。它连 `SOLVER_ONLY` 那一档都不该占——它根本不是
    用户填的，是系统数出来的。

    `major` 和 `confirmed_events` 曾经也在这里，是被**显式提拔**出去的：
    前者撑起「你们三个不同专业」，后者撑起「他有两次已确认的交付记录」，
    没有后者 M4 的闭环判据无从谈起。提拔的理由写在 `GRANTABLE_FIELDS` 旁边。
    """
    assert UNGRANTABLE == DELIBERATELY_UNGRANTABLE
    assert "active_commitments" in UNGRANTABLE
    assert attributes_visible_under(frozenset({"active_commitments"})) == frozenset()


def test_the_default_objectives_all_have_somewhere_to_go() -> None:
    """契约给的六个软目标，每一个要么写成句子，要么留在 notes 里。

    默默丢掉一个目标项，界面上就少一条依据而没人会发现。
    """
    contributions = tuple(
        ObjectiveContribution(o.kind, 1.0, o.weight, f"{o.kind.value} 贡献")
        for o in _default_objectives()
    )
    group, requirement, verdict = _case(contributions=contributions)
    proof = build(group, requirement, verdict, now=NOW, visible_fields=ALL_VISIBLE)

    for contribution in contributions:
        assert any(contribution.kind.value in note for note in proof.notes)


def _default_objectives() -> tuple[Objective, ...]:
    from cofield.matching.contracts import DEFAULT_OBJECTIVES

    return DEFAULT_OBJECTIVES
