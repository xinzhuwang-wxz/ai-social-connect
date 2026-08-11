"""意图的领域规则与抽取。

这里守住的核心是那道门：**未经用户确认的抽取不得进入撮合**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cofield.adapters.extraction import RuleIntentExtractor
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)  # 周三
FRIDAY = datetime(2026, 8, 14, 23, 59, tzinfo=UTC)
TTL = timedelta(days=3)


def content(**over: object) -> IntentContent:
    base: dict[str, object] = {
        "goal": "周五前完成 60 秒校园流浪猫短片",
        "offers": ("脚本",),
        "needs": ("拍摄", "剪辑"),
        "time_window": TimeWindow(earliest=NOW, deadline=FRIDAY),
        "team_size": TeamSize(minimum=3, maximum=4),
    }
    base.update(over)
    return IntentContent(**base)  # type: ignore[arg-type]


def signal(state: IntentState = IntentState.DRAFT, **over: object) -> IntentSignal:
    return IntentSignal(
        id=uuid4(),
        principal_id=uuid4(),
        state=state,
        raw_expression="想拍个流浪猫短片，周五前完成",
        content=content(**over),
        created_at=NOW,
    )


# --- 那道门 ---


def test_a_draft_never_participates_in_matching() -> None:
    assert not signal(IntentState.DRAFT).is_matchable


def test_a_stash_never_participates_in_matching() -> None:
    """念头是给自己看的，不进撮合，也不进任何公共列表。"""
    assert not signal(IntentState.STASHED).is_matchable


def test_only_a_confirmed_intent_becomes_matchable() -> None:
    confirmed = signal().confirm(now=NOW, ttl=TTL)

    assert confirmed.state is IntentState.ACTIVE
    assert confirmed.is_matchable


def test_editing_sends_it_back_for_confirmation() -> None:
    """改了内容就得重新确认——旧的确认不能沿用到新内容上。"""
    active = signal().confirm(now=NOW, ttl=TTL)

    revised = active.revise(content(goal="改成两分钟"))

    assert revised.state is IntentState.DRAFT
    assert not revised.is_matchable


def test_withdrawn_intent_stops_matching() -> None:
    assert not signal().confirm(now=NOW, ttl=TTL).withdraw().is_matchable


# --- 过期 ---


def test_expiry_never_outlives_the_deadline() -> None:
    """TTL 再长也不该活过用户自己的截止时间——那之后配上也没意义。"""
    confirmed = signal().confirm(now=NOW, ttl=timedelta(days=30))

    assert confirmed.expires_at == FRIDAY


def test_expiry_falls_back_to_ttl_without_a_deadline() -> None:
    confirmed = signal(time_window=None, team_size=None, needs=()).confirm(
        now=NOW, ttl=TTL
    )

    assert confirmed.expires_at == NOW + TTL


def test_is_expired_uses_the_injected_instant() -> None:
    confirmed = signal().confirm(now=NOW, ttl=TTL)

    assert not confirmed.is_expired(now=FRIDAY - timedelta(minutes=1))
    assert confirmed.is_expired(now=FRIDAY)


# --- 自相矛盾 ---


def test_a_past_deadline_is_reported_not_silently_accepted() -> None:
    stale = content(
        time_window=TimeWindow(
            earliest=NOW - timedelta(days=5), deadline=NOW - timedelta(days=1)
        )
    )

    conflicts = stale.conflicts(now=NOW)

    assert [c.field for c in conflicts] == ["time_window"]
    assert "来不及" in conflicts[0].detail


def test_a_team_too_small_for_its_own_role_gaps_is_reported() -> None:
    cramped = content(needs=("拍摄", "剪辑", "配乐"), team_size=TeamSize(2, 2))

    conflicts = cramped.conflicts(now=NOW)

    assert [c.field for c in conflicts] == ["team_size"]
    assert "至少 4 人" in conflicts[0].detail


def test_the_same_skill_cannot_be_both_offered_and_needed() -> None:
    conflicts = content(offers=("剪辑",), needs=("剪辑",)).conflicts(now=NOW)

    assert [c.field for c in conflicts] == ["needs"]


def test_all_conflicts_are_reported_at_once() -> None:
    """用户想一次改完，不想改一个再被告知还有一个。"""
    broken = IntentContent(
        goal="   ",
        offers=("剪辑",),
        needs=("剪辑",),
        time_window=TimeWindow(
            earliest=NOW - timedelta(days=5), deadline=NOW - timedelta(days=1)
        ),
    )

    assert {c.field for c in broken.conflicts(now=NOW)} == {
        "goal",
        "time_window",
        "needs",
    }


def test_confirming_a_conflicted_intent_is_refused() -> None:
    conflicted = signal(offers=("剪辑",), needs=("剪辑",))

    with pytest.raises(ValueError, match="冲突"):
        conflicted.confirm(now=NOW, ttl=TTL)


# --- 值对象 ---


def test_a_time_window_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValueError, match="截止时间不能早于"):
        TimeWindow(earliest=FRIDAY, deadline=NOW)


def test_a_team_of_one_is_refused() -> None:
    with pytest.raises(ValueError, match="至少两个人"):
        TeamSize(minimum=1, maximum=3)


# --- 抽取 ---


def test_the_canonical_sentence_extracts_both_role_gaps() -> None:
    """否定式说法（"不认识会拍摄和剪辑的人"）表达的其实是需求。"""
    result = RuleIntentExtractor().extract(
        "我想做一个关于校园流浪猫的一分钟短片，周五前完成。"
        "我会写脚本，但不认识会拍摄和剪辑的人。",
        now=NOW,
    )

    assert result.content.needs == ("拍摄", "剪辑")
    assert result.content.offers == ("写脚本",)
    assert result.content.time_window is not None
    assert result.content.time_window.deadline.date() == FRIDAY.date()


def test_extraction_never_asks_more_than_two_questions() -> None:
    """多于两个追问，说明抽取器在把自己的不确定推给用户。"""
    result = RuleIntentExtractor().extract("随便看看", now=NOW)

    assert len(result.follow_ups) <= 2


def test_follow_ups_only_narrow_the_feasible_set() -> None:
    """每个追问都必须指向一个能实质改变可行集合的字段。"""
    result = RuleIntentExtractor().extract("随便看看", now=NOW)

    assert {q.narrows for q in result.follow_ups} <= {
        "time_window",
        "needs",
        "location_scope",
        "team_size",
    }


def test_inferred_values_are_marked_uncertain_not_presented_as_fact() -> None:
    result = RuleIntentExtractor().extract("缺一个会剪辑的，明天要", now=NOW)

    assert result.content.team_size is not None
    assert "team_size" in result.content.uncertain_fields


def test_a_vague_expression_yields_low_confidence() -> None:
    """置信度低时界面直接退回手填表单，而不是拿一份瞎猜的结构去配队。"""
    assert RuleIntentExtractor().extract("随便看看", now=NOW).confidence < 0.5


def test_boundary_hints_become_open_questions_not_settled_constraints() -> None:
    """"署名要说清楚"是**要留给真人决定的事**，不是已经定下的约束。"""
    result = RuleIntentExtractor().extract("招两个前端，署名要说清楚", now=NOW)

    assert "署名规则" in result.content.open_questions
    assert result.content.boundaries == ()
