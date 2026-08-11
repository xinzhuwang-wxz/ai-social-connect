"""凑不出队的时候说什么。

这里断言的不是"能返回一个错误"，而是**这句话对用户有没有用**：
它有没有说清卡在哪、有没有给真数字、有没有可以点的下一步、
有没有在该提醒的时候提醒。

跑在真的两万人上——放宽收益必须是真查出来的数字，估的没有意义。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.catalog import registry
from cofield.domain.model.action_kind import RiskTier
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.matching.blocking import (
    Stage,
    StepKind,
    explain_formation,
    explain_recall,
)
from cofield.matching.contracts import ConstraintKind, HardConstraint, SolveResult
from cofield.matching.funnel import Funnel
from cofield.simulation.loader import load_principals
from cofield.simulation.population import generate

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
SIM = "simulation"
SIZE = 4_000

HIGH_RISK = next(k for k in registry.all() if k.risk_tier is RiskTier.HIGH)
LOW_RISK = next(k for k in registry.all() if k.risk_tier is RiskTier.LOW)


@pytest.fixture(scope="module")
def campus(engine: Engine):  # type: ignore[no-untyped-def]
    """fixture 必须叫 `campus`——conftest 的清表钩子靠这个名字保住人口。"""
    population = generate(size=SIZE, seed=5)
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals CASCADE"))
    load_principals(engine, population, campus_id=SIM, now=NOW)
    yield population
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals CASCADE"))


def _intent(needs: tuple[str, ...], place: str | None = None) -> IntentSignal:
    return IntentSignal(
        id=uuid4(),
        principal_id=uuid4(),
        state=IntentState.ACTIVE,
        raw_expression="想找几个人一起做点事",
        content=IntentContent(
            goal="做一件事",
            offers=("写文案",),
            needs=needs,
            time_window=TimeWindow(NOW, NOW + timedelta(days=3)),
            location_scope=place,
            team_size=TeamSize(3, 4),
        ),
        created_at=NOW,
    )


def _blocked(engine: Engine, intent: IntentSignal):  # type: ignore[no-untyped-def]
    """跑一次真的漏斗，拿到真的阻塞诊断与真的放宽收益。"""
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM)
        result = funnel.shortlist(intent, now=NOW)
        assert result.candidates == (), "这个用例需要一个真的无解场景"
        return explain_recall(
            funnel, intent, result.trace.blocked_by, kind=LOW_RISK
        ), funnel


# --- 不伪造 ---


def test_no_candidates_are_invented_when_there_is_no_answer(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """凑几个不合适的人交差，比说"凑不出来"伤害大得多。

    用户会真的去联系他们，然后发现全是浪费。
    """
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(_intent(("焊接",)), now=NOW)

    assert result.candidates == ()
    assert result.trace.after_recall == 0


def test_it_says_which_constraints_jointly_caused_it(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """要说清是哪几条**共同**导致的，不是只说"没找到"。"""
    proof, _ = _blocked(engine, _intent(("焊接",)))

    assert proof.stage is Stage.RECALL
    assert proof.causes
    assert "会做这几件事的人" in proof.causes


# --- 数字必须是真的 ---


def test_every_relaxation_carries_a_real_number(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """「可以试试放宽条件」等于什么都没说。

    放开校区多出 137 个人还是多出 2 个，用户的决定完全不同。
    """
    proof, _ = _blocked(engine, _intent(("焊接",), "南校区"))

    assert proof.relaxations
    assert all(isinstance(r.gains, int) for r in proof.relaxations)
    assert any(r.gains > 0 for r in proof.relaxations)
    assert re.search(r"\d+ 个人", proof.statement), (
        f"这句话里没有具体数字：{proof.statement}"
    )


def test_the_highlighted_option_is_the_one_that_buys_the_most(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    proof, _ = _blocked(engine, _intent(("焊接",), "南校区"))
    best = proof.best_relaxation

    assert best is not None
    assert best.gains == max(
        r.gains for r in proof.relaxations if r.advisable
    )


def test_relaxation_numbers_come_from_a_real_requery(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """证明这个数字不是编的：卸掉那一条真的能查到那么多人。"""
    intent = _intent(("调色",), "南校区")
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM)
        gain = funnel.relaxation_gain(intent, "location_scope")
        narrow = funnel.shortlist(intent, now=NOW).trace.after_hard_filter
        wide = funnel.shortlist(_intent(("调色",)), now=NOW).trace.after_hard_filter

    assert gain == wide - narrow


# --- 该提醒的时候提醒 ---


def _zone_and_size_blocked() -> SolveResult:
    """人都在，但不在同一个校区、也凑不够人数。

    这是地点与人数两项放宽真正出现的场景。召回段见不到它们——
    两万人的校园里全校有人会的技能每个校区都有人会（实测如此），
    单独放开校区一个人都多不出来。
    """
    return SolveResult(
        groups=(),
        blocked_by=(
            HardConstraint(ConstraintKind.ZONE, "三个人分在两个校区"),
            HardConstraint(ConstraintKind.TEAM_SIZE, "只凑到 2 个人"),
        ),
    )


def test_dangerous_relaxations_are_flagged_but_still_offered(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """不列出来等于替用户做决定；不标记等于没尽到提醒的责任。

    两者都不对——所以照列，但明说担心的是什么。
    """
    proof = explain_formation(_zone_and_size_blocked(), kind=HIGH_RISK)
    flagged = {r.field_name: r for r in proof.relaxations}

    assert set(flagged) == {"location_scope", "team_size"}
    for relaxation in flagged.values():
        assert relaxation.advisable is False
        assert relaxation.caution, "标了不建议却不说为什么，等于没标"
        assert "安全" not in relaxation.caution, (
            "「出于安全考虑」是废话，要说具体担心什么"
        )


def test_ordinary_activities_are_not_blanketed_with_warnings(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """把所有放宽都标成"注意安全"等于没有标记——用户会一律忽略。

    同一个卡点，低风险类别下一条提醒都不该有。
    """
    proof = explain_formation(_zone_and_size_blocked(), kind=LOW_RISK)

    assert proof.relaxations
    assert all(r.advisable for r in proof.relaxations)
    assert all(not r.caution for r in proof.relaxations)


# --- 下一步必须能点 ---


def test_there_is_always_something_to_do_next(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    proof, _ = _blocked(engine, _intent(("焊接",)))
    kinds = {s.kind for s in proof.next_steps}

    assert StepKind.WAIT_FOR_SUPPLY in kinds, "还有时间的话，等市场变厚往往更划算"
    assert StepKind.ASK_ORGANIZERS in kinds
    assert all(s.invitation for s in proof.next_steps)


def test_running_out_of_options_still_leaves_a_way_forward(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """一个可放宽项都没有时，也不能停在死路上。"""
    intent = _intent(())
    with campus_connection(engine, SIM) as conn:
        proof = explain_recall(Funnel(conn, SIM), intent, (), kind=LOW_RISK)

    assert proof.next_steps
    assert proof.statement


# --- 两种凑不出来是两回事 ---


def test_having_nobody_and_having_nobody_who_fits_together_read_differently(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """混成一句"没找到合适的人"，会让第二种情况的用户白白放弃——
    他们其实只差一个时间段。"""
    recall, _ = _blocked(engine, _intent(("焊接",)))
    formation = explain_formation(
        SolveResult(
            groups=(),
            blocked_by=(
                HardConstraint(ConstraintKind.COMMON_TIME, "四个人凑不出连续两段"),
            ),
        ),
        kind=LOW_RISK,
    )

    assert formation.stage is Stage.FORMATION
    assert formation.statement != recall.statement
    assert "连着的共同空闲" in formation.statement


def test_a_time_only_blockage_says_so_plainly(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """只差时间时，别说得像是没人愿意来。"""
    proof = explain_formation(
        SolveResult(
            groups=(),
            blocked_by=(HardConstraint(ConstraintKind.COMMON_TIME, "凑不出连续两段"),),
        )
    )

    assert proof.statement.startswith("合适的人都在")


# --- 文案 ---


def _domain_terms() -> set[str]:
    """从 CONTEXT.md 抓术语表。

    手抄一份清单迟早和文档漂移——这是 07 §2.1 明确要求的做法。
    """
    text = (Path(__file__).resolve().parents[3] / "CONTEXT.md").read_text("utf-8")
    terms = set(re.findall(r"^\*\*([^*（\n]+)（", text, re.M))
    assert len(terms) > 20, "没抓到术语表，路径大概写错了"
    return terms


_EXTRA_LEAKS = (
    "意图", "主体", "切面", "共域", "漏斗", "求解", "约束", "提案",
    "授权", "撮合", "稳定性", "代理", "智能体", "凭证", "信封", "召回",
)


def test_the_words_are_the_users_words(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """界面上不出现领域词汇。这条能被机器检查，不该靠 review 凭感觉抓。"""
    intent = _intent(("焊接",), "南校区")
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM)
        blocked = funnel.shortlist(intent, now=NOW).trace.blocked_by
        proofs = [
            explain_recall(funnel, intent, blocked, kind=HIGH_RISK),
            explain_formation(_zone_and_size_blocked(), kind=HIGH_RISK),
        ]

    banned = _domain_terms() | set(_EXTRA_LEAKS)
    visible: list[str] = []
    for proof in proofs:
        visible.append(proof.statement)
        visible.extend(proof.causes)
        visible.extend(r.invitation for r in proof.relaxations)
        visible.extend(r.caution for r in proof.relaxations)
        visible.extend(s.invitation for s in proof.next_steps)

    for line in visible:
        leaked = [t for t in banned if t in line]
        assert not leaked, f"「{line}」里漏了领域词汇：{leaked}"


def test_the_copy_neither_consoles_nor_reports_an_error(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """"很遗憾"是安慰，"未找到匹配结果"是报错。两种都没说下一步能干什么。"""
    proof, _ = _blocked(engine, _intent(("焊接",), "南校区"))

    for phrase in ("很遗憾", "抱歉", "失败", "错误", "未找到", "无结果"):
        assert phrase not in proof.statement
