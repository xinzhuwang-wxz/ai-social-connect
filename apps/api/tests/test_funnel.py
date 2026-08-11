"""合成校园与漏斗前两段。

跑在真的两万人上。这里断言的不是"能筛"，而是**筛得对**——
稀缺角色真的成为瓶颈、时间约束真的咬人、凑不出队时说得出卡在哪。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.matching.funnel import Funnel, contiguous_common_slots
from cofield.simulation.loader import load_principals
from cofield.simulation.population import (
    SKILL_ABUNDANCE,
    arrivals,
    fingerprint,
    generate,
)

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
SIM = "simulation"
SIZE = 20_000


@pytest.fixture(scope="module")
def campus(engine: Engine):  # type: ignore[no-untyped-def]
    """整个模块共用一份两万人。装一次 0.7 秒，不值得每个用例重来。"""
    import sqlalchemy as sa

    population = generate(size=SIZE)
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
        raw_expression="想拍支短片",
        content=IntentContent(
            goal="拍一支 60 秒短片",
            offers=("写脚本",),
            needs=needs,
            time_window=TimeWindow(NOW, NOW + timedelta(days=3)),
            location_scope=place,
            team_size=TeamSize(3, 4),
        ),
        created_at=NOW,
    )


# --- 人口结构：随机会把系统测得过于乐观 ---


def test_skills_are_long_tailed_so_scarce_roles_really_bottleneck(campus) -> None:  # type: ignore[no-untyped-def]
    counts = campus.scarcity()
    values = list(counts.values())

    assert values[-1] / max(values[0], 1) > 20, "最充裕与最稀缺的差距不足一个数量级"
    assert values[0] < SIZE * 0.02, "最稀缺的技能仍有 2% 以上的人，长尾没生效"


def test_availability_is_constrained_enough_to_bite(campus) -> None:  # type: ignore[no-untyped-def]
    """真正咬人的是「整组连续两段共同空闲」，不是「任意一段重合」。

    任意一段几乎总能凑上；连续两段在四人组只有约一半能成。时间约束
    必须按后者算，否则它形同虚设。
    """
    import random

    rng = random.Random(11)
    people = campus.people

    any_slot = sum(
        contiguous_common_slots([p.availability for p in rng.sample(people, 4)], run=1)
        > 0
        for _ in range(300)
    )
    two_in_a_row = sum(
        contiguous_common_slots([p.availability for p in rng.sample(people, 4)], run=2)
        > 0
        for _ in range(300)
    )

    # 实测（种子固定后跨进程稳定）：单段 292/300，连续两段 148/300。
    # 阈值留出余量——贴着实测值划会让人口的任何一点合理演进都变成红灯，
    # 而这条用例要守的是"单段不是约束、两段是"这个**性质**，不是那两个数。
    assert any_slot > 270, "单段重合应该几乎总能凑上"
    assert 60 < two_in_a_row < 240, "连续两段应该是真约束，既不总成也不总败"


def test_the_history_layers_match_the_design(campus) -> None:  # type: ignore[no-untyped-def]
    """45% 零历史那一层是用来验证冷启动公平的。"""
    from collections import Counter

    tiers = Counter(p.history_tier for p in campus.people)

    assert 0.42 < tiers[0] / SIZE < 0.48
    assert 0.32 < tiers[1] / SIZE < 0.38
    assert 0.17 < tiers[2] / SIZE < 0.23


#: 五百人、种子 7 的人口指纹。
#:
#: **写死一个常量，而不是跑两次比一比。** 原来那条测试在同一个进程里
#: 生成两份再比较——进程内哈希盐相同，所以它永远相等，也就永远发现不了
#: 真正的问题：课表用了内置 `hash()`，而 Python 的字符串哈希每个进程加
#: 不同的盐，同一个种子在两次运行里生成的是两份不同的课表。
#:
#: 这个洞让"给定种子完全可复现"这句话在很长一段时间里是假的，
#: 而所有实测数字（四人组 45%、七倍富集）都只是某一次运行的巧合。
POPULATION_FINGERPRINT = "2e8db6f16aa85335ee2952ad49bf288b"


def test_generation_is_reproducible_across_processes() -> None:
    """仿真结论必须能被重跑验证。

    指纹变了就是生成器变了：要么是有意改的（更新这个常量，
    并在提交信息里说清改了什么），要么是又漏进了一处进程相关的随机性。
    """
    assert fingerprint(generate(size=500, seed=7)) == POPULATION_FINGERPRINT


def test_the_fingerprint_actually_catches_a_difference() -> None:
    """指纹本身要能失败，否则上面那条又是一次自欺。"""
    assert fingerprint(generate(size=500, seed=7)) != fingerprint(
        generate(size=500, seed=8)
    )


def test_arrivals_cluster_before_their_deadlines(campus) -> None:  # type: ignore[no-untyped-def]
    """均匀到达会让撮合窗口的效果测错。"""
    intents = arrivals(campus, now=NOW, count=400)

    # 量的是"此刻距截止还有多久"，不是"从创建到截止的总跨度"——
    # 后者恒大于前者，测它等于什么都没测。
    # 截止时刻落在当天 23:59，所以"三天后截止"距今是 3.6 天——阈值取 4 天。
    remaining = [(i.deadline - NOW).total_seconds() / 86400 for i in intents]
    urgent = sum(1 for d in remaining if d <= 4)

    assert len(intents) == 400
    assert urgent / len(remaining) > 0.4, "紧急意图太少，到达没有贴着截止期"
    assert max(remaining) > 10, "全都很急也不真实，长尾要在"


def test_expressions_vary_in_quality(campus) -> None:  # type: ignore[no-untyped-def]
    """全是标准句式的话，意图理解的失败路径根本测不到。"""
    intents = arrivals(campus, now=NOW, count=400)
    lengths = {len(i.expression) for i in intents}

    assert len(lengths) > 20, "表达长度过于集中，质量没有参差"
    assert any("不认识会" in i.expression for i in intents), "缺少否定式表达"


# --- 漏斗 ---


def test_the_funnel_narrows_by_orders_of_magnitude(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(_intent(("拍摄", "剪辑")), now=NOW)

    assert result.trace.population == SIZE
    assert 0 < result.trace.after_recall <= 40
    assert result.trace.after_recall < result.trace.after_hard_filter


def test_a_scarce_role_really_shrinks_the_pool(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """会调色的只有两百来人，加上校区就剩几十——这才是真瓶颈。"""
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM)
        common = funnel.shortlist(_intent(("写文案",)), now=NOW)
        scarce = funnel.shortlist(_intent(("调色",), "南校区"), now=NOW)

    assert scarce.trace.after_hard_filter < common.trace.after_hard_filter / 5


def test_an_impossible_need_says_which_constraint_blocked_it(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """不能只说"没找到"——要说清是哪一条把人筛没了。"""
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(_intent(("焊接",)), now=NOW)

    assert result.candidates == ()
    assert "needs" in result.trace.blocked_by


def test_relaxing_a_constraint_reports_how_many_more_it_buys(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """阻塞证明要给具体数字，不是"可以试试放宽条件"。"""
    with campus_connection(engine, SIM) as conn:
        gain = Funnel(conn, SIM).relaxation_gain(
            _intent(("调色",), "南校区"), "location_scope"
        )

    assert gain > 0


def test_the_requester_is_never_their_own_candidate(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    intent = _intent(("拍摄",))
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(intent, now=NOW)

    assert intent.principal_id not in {c.principal_id for c in result.candidates}


def test_blocked_candidates_are_excluded(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    with campus_connection(engine, SIM) as conn:
        funnel = Funnel(conn, SIM)
        first = funnel.shortlist(_intent(("拍摄", "剪辑")), now=NOW)
        blocked = frozenset({first.candidates[0].principal_id})
        second = funnel.shortlist(_intent(("拍摄", "剪辑")), now=NOW, exclude=blocked)

    assert blocked.isdisjoint({c.principal_id for c in second.candidates})


def test_every_candidate_covers_at_least_one_gap(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """补不上洞的人来了也没用——硬约束不该放他们过来。"""
    needs = {"拍摄", "剪辑"}
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(_intent(tuple(needs)), now=NOW)

    assert result.candidates
    for candidate in result.candidates:
        assert needs & set(candidate.skills)


def test_recall_puts_wider_coverage_first(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """排序信号只有可解释的两个：补上几个缺口、时间多宽裕。"""
    needs = {"拍摄", "剪辑"}
    with campus_connection(engine, SIM) as conn:
        result = Funnel(conn, SIM).shortlist(_intent(tuple(needs)), now=NOW)

    covered = [len(needs & set(c.skills)) for c in result.candidates]
    assert covered == sorted(covered, reverse=True)


def test_synthetic_population_stays_inside_its_tenant(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """两万合成主体在真实租户里一个都看不到。"""
    with campus_connection(engine, "demo-campus") as conn:
        result = Funnel(conn, "demo-campus").shortlist(_intent(("拍摄",)), now=NOW)

    assert result.trace.population == 0
    assert result.candidates == ()


def test_every_skill_in_the_vocabulary_has_someone(campus) -> None:  # type: ignore[no-untyped-def]
    """词表里的技能一个都不能是空的，否则那一类需求永远无解。"""
    counts = campus.scarcity()

    assert set(counts) == set(SKILL_ABUNDANCE)
    assert all(n > 0 for n in counts.values())
