"""窗口清算。

这里断言的不是"到点会跑"，而是**攒着解真的和逐条解不一样**：
六条需求抢四十来个会调色的人，逐条求解时先提交的把人占走，
批量清算把同一个人被提案的次数压到上限。这是整个"按窗口清算"的论点，
测不出差别就说明这个选择没有依据，该删掉。

时间全部由 `SimulatedClock` 推动，一次 `sleep` 都没有——
"快进两周"必须是产品能力，不是靠真等。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.adapters.persistence.engine import campus_connection, owner_connection
from cofield.adapters.persistence.intents import IntentRepository
from cofield.adapters.persistence.proposals import ProposalRepository
from cofield.catalog import registry
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.matching.window import (
    EPOCH,
    MAX_PROPOSALS_PER_ROUND,
    Clearing,
    MarketBoard,
    MarketUnit,
)
from cofield.simulation.loader import load_principals
from cofield.simulation.population import generate

NOW = datetime(2026, 8, 12, 9, tzinfo=UTC)
SIM = "simulation"
SIZE = 3_000
KIND = "creative_work"


@pytest.fixture(scope="module")
def campus(engine: Engine):  # type: ignore[no-untyped-def]
    """fixture 必须叫 `campus`——conftest 的清表钩子靠这个名字保住人口。"""
    population = generate(size=SIZE, seed=9)
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals CASCADE"))
    load_principals(engine, population, campus_id=SIM, now=NOW)
    yield population
    with owner_connection(engine) as conn:
        conn.execute(sa.text("TRUNCATE principals, formation_proposals CASCADE"))


@pytest.fixture(autouse=True)
def _clear_market(engine: Engine):  # type: ignore[no-untyped-def]
    """意图与提案每个用例之间清掉，人口留着。"""
    yield
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE intent_signals, formation_proposals, seed_deliveries CASCADE"
            )
        )


def _intent(
    principal_id: UUID,
    *,
    created_at: datetime,
    deadline: datetime,
    needs: tuple[str, ...] = ("拍摄", "剪辑"),
    kind: str | None = KIND,
) -> IntentSignal:
    return IntentSignal(
        id=uuid4(),
        principal_id=principal_id,
        state=IntentState.ACTIVE,
        raw_expression="想拍支短片，缺个会剪的",
        content=IntentContent(
            goal="拍一支 60 秒短片",
            offers=("写脚本",),
            needs=needs,
            time_window=TimeWindow(created_at, deadline),
            location_scope=None,
            team_size=TeamSize(2, 4),
        ),
        created_at=created_at,
        action_kind=kind,
    )


def _save(engine: Engine, *intents: IntentSignal, now: datetime) -> None:
    with campus_connection(engine, SIM) as conn:
        repo = IntentRepository(conn, SimulatedClock(now), SIM)
        for intent in intents:
            repo.save(intent)


def _clear(engine: Engine, *, now: datetime):  # type: ignore[no-untyped-def]
    with campus_connection(engine, SIM) as conn:
        return Clearing(conn, SIM, registry).run(now=now)


# --- 清算时刻是共享的 ---


def test_clearing_times_are_shared_not_per_person() -> None:
    """"提交后 6 小时"会让争用根本不被看见。

    每个人各自计时的话，大家仍然是各自到点各自撮合，只是都多等了六小时。
    共同的清算时刻才是"能看见谁在抢谁"的前提。
    """
    unit = MarketUnit(SIM, KIND, timedelta(hours=6))
    early = unit.next_clearing(datetime(2026, 8, 12, 1, 30, tzinfo=UTC))
    late = unit.next_clearing(datetime(2026, 8, 12, 5, 59, tzinfo=UTC))

    assert early == late, "同一个窗口里的人必须清算在同一时刻"
    assert (early - EPOCH) % timedelta(hours=6) == timedelta(0), "边界没对齐"


def test_each_kind_can_wait_a_different_length(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """窗口长度由行动类别声明，不是全局常量。

    组队打比赛和周末爬山不该被塞进同一个节奏。
    """
    with campus_connection(engine, SIM) as conn:
        board = MarketBoard(conn, SIM, registry)
        windows = {k.key: board.unit_for(k.key).window for k in registry.all()}

    assert len(set(windows.values())) > 1, "所有类别窗口一样长，等于没有这个扩展点"


def test_unclassified_intents_still_get_cleared(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """用户可以不挑场景直接写一句话。不能因为"没归类"就永远不撮合。

    `NULL = NULL` 在 SQL 里不成立，这条最容易被写成静默返回空集。
    """
    person = campus.people[0]
    _save(
        engine,
        _intent(
            person.id,
            created_at=NOW - timedelta(hours=12),
            deadline=NOW + timedelta(days=7),
            kind=None,
        ),
        now=NOW,
    )
    report = _clear(engine, now=NOW)

    assert report.considered == 1


# --- 等待换来什么 ---


def test_batching_stops_one_person_from_being_everyones_answer(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """这是「按窗口清算」真正买到的东西。

    候选来自全校静态人口，多等六小时不会让会调色的人变多——所以等待
    **不是**为了让候选变厚，那条说法经不起推敲。它买到的是「看得见争用」：
    逐条求解时每条都对着全校独立解，谁先提交谁把稀缺的人占走；
    攒着一起解，系统才第一次看见这几个人在抢同一批人。

    二十条都缺调色的需求，三千人里只有四十来个会调色的。

    条数要够多才抢得起来：一条种子只投给三个人，六条一共十八份，
    在四十个候选里几乎不重叠——**那时候这个用例什么都没测到**。
    """
    people = campus.people[:20]
    intents = [
        _intent(
            p.id,
            created_at=NOW - timedelta(hours=12),
            deadline=NOW + timedelta(days=7),
            needs=("调色",),
        )
        for p in people
    ]

    # 逐条：来一条解一条。
    for intent in intents:
        _save(engine, intent, now=NOW)
        _clear(engine, now=NOW)
    greedy = _exposure(engine)
    with owner_connection(engine) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE intent_signals, formation_proposals, seed_deliveries CASCADE"
            )
        )

    # 批量：攒齐了一起解。
    _save(engine, *intents, now=NOW)
    _clear(engine, now=NOW)
    batched = _exposure(engine)

    assert max(greedy.values()) > MAX_PROPOSALS_PER_ROUND, (
        "逐条求解没有出现争用，这个用例就没测到东西——换更稀缺的角色"
    )
    assert max(batched.values()) <= MAX_PROPOSALS_PER_ROUND
    assert len(batched) >= len(greedy), "分配之后被提案的人反而更少了"


def _exposure(engine: Engine) -> Counter[UUID]:
    """一个人这一轮收到了几颗**不同需求**的种子。

    投递制之后（ADR 0010）这里数的是投递，不是提案——但要防的东西没变：
    一个人被当成六条需求的答案，他会收到六颗种子，而那和收到垃圾邮件
    没有区别。
    """
    with campus_connection(engine, SIM) as conn:
        rows = conn.execute(
            sa.text("SELECT intent_id, principal_id FROM seed_deliveries")
        ).all()
    seen: dict[UUID, set[UUID]] = {}
    for row in rows:
        seen.setdefault(row.principal_id, set()).add(row.intent_id)
    return Counter({k: len(v) for k, v in seen.items()})


def test_intents_submitted_after_the_boundary_keep_waiting(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """边界之后才提交的人继续等。

    他们的等待正是让下一次能看见争用的原因——立刻给他们清算，
    等于又退回到逐条求解。
    """
    unit = MarketUnit(SIM, KIND, registry.get(KIND).matching_window)
    boundary = unit.previous_clearing(NOW)
    person = campus.people[10]

    _save(
        engine,
        _intent(
            person.id,
            created_at=boundary + timedelta(minutes=1),
            deadline=NOW + timedelta(days=7),
        ),
        now=NOW,
    )
    report = _clear(engine, now=NOW)

    assert report.considered == 0


# --- 谁不用等 ---


def test_people_who_would_leave_before_the_next_clearing_go_now(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """截止期落在下次清算之前的人，立刻清算。

    这条不是拍的阈值：到清算时他已经离开市场了，等待对他**严格更差**。
    """
    unit = MarketUnit(SIM, KIND, registry.get(KIND).matching_window)
    person = campus.people[20]

    _save(
        engine,
        _intent(
            person.id,
            # 刚提交，本该继续等
            created_at=NOW,
            # 但等不到下次清算了
            deadline=unit.next_clearing(NOW) - timedelta(minutes=5),
        ),
        now=NOW,
    )
    report = _clear(engine, now=NOW)

    assert report.early == 1
    assert report.considered == 1


# --- 时钟推动 ---


def test_advancing_the_clock_makes_clearing_happen(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """推进时钟就能观察到清算，不用真等，也不用 sleep。"""
    unit = MarketUnit(SIM, KIND, registry.get(KIND).matching_window)
    boundary = unit.previous_clearing(NOW)
    person = campus.people[30]

    _save(
        engine,
        _intent(
            person.id,
            created_at=boundary + timedelta(minutes=1),
            deadline=NOW + timedelta(days=30),
        ),
        now=NOW,
    )

    clock = SimulatedClock(NOW)
    assert _clear(engine, now=clock.now()).considered == 0

    clock.advance(unit.window)
    assert _clear(engine, now=clock.now()).considered == 1


def test_running_twice_in_the_same_window_does_not_duplicate(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """清算重复调用是安全的。

    `cleared_at` 记的是**边界时刻**而不是"跑这一次的时刻"，所以同一个窗口内
    幂等。投递制之后这一条更要紧了：不幂等的后果不是"多出一支队"，
    是候选那一侧收到一封又一封"有人想找你"——像垃圾邮件。
    """
    person = campus.people[40]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    _save(engine, intent, now=NOW)

    _clear(engine, now=NOW)
    after_one = _delivered(engine, intent.id)
    second = _clear(engine, now=NOW)

    assert after_one, "第一次就没投出去，这个用例测不到东西"
    assert _delivered(engine, intent.id) == after_one, "重跑一次又投了一批"
    assert second.proposed == 0


def _delivered(engine: Engine, intent_id: UUID) -> set[UUID]:
    with campus_connection(engine, SIM) as conn:
        rows = conn.execute(
            sa.text(
                "SELECT principal_id FROM seed_deliveries WHERE intent_id = :i"
            ),
            {"i": intent_id},
        ).all()
    return {r.principal_id for r in rows}


# --- 等待期间看得到什么 ---


def test_waiting_is_not_a_blank_screen(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """光说"请稍候"用户只会走掉。

    要能说出下次什么时候配队、这个方向上现在缺什么。
    """
    people = campus.people[50:56]
    _save(
        engine,
        *[
            _intent(
                p.id,
                created_at=NOW - timedelta(hours=1),
                deadline=NOW + timedelta(days=7),
            )
            for p in people
        ],
        now=NOW,
    )

    with campus_connection(engine, SIM) as conn:
        pulse = MarketBoard(conn, SIM, registry).pulse(KIND, now=NOW)

    assert pulse.waiting == 6
    assert pulse.next_clearing_at > NOW
    assert pulse.gaps
    assert any(g.scarce for g in pulse.gaps), "六个人都缺剪辑，这该是稀缺的"


def test_the_pulse_names_no_names(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """"缺什么"是公共信息，"谁在等"不是。"""
    person = campus.people[60]
    _save(
        engine,
        _intent(
            person.id,
            created_at=NOW - timedelta(hours=1),
            deadline=NOW + timedelta(days=7),
        ),
        now=NOW,
    )

    with campus_connection(engine, SIM) as conn:
        pulse = MarketBoard(conn, SIM, registry).pulse(KIND, now=NOW)

    rendered = repr(pulse)
    assert person.display_name not in rendered
    assert str(person.id) not in rendered


def test_the_scarcest_gap_comes_first(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """用户最需要知道的是"最难补的是哪一样"。"""
    people = campus.people[70:78]
    _save(
        engine,
        *[
            _intent(
                p.id,
                created_at=NOW - timedelta(hours=1),
                deadline=NOW + timedelta(days=7),
                needs=("调色",) if i < 6 else ("写文案",),
            )
            for i, p in enumerate(people)
        ],
        now=NOW,
    )

    with campus_connection(engine, SIM) as conn:
        pulse = MarketBoard(conn, SIM, registry).pulse(KIND, now=NOW)

    assert pulse.gaps[0].skill == "调色"


# --- 不变量 ---


def test_no_proposal_survives_a_failed_stability_check(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """稳定性未通过的分区**不得成为提案**。三条不可越过之一。

    所以库里不该存在 stability_passed 为假的行——过滤发生在写库之前，
    不是写完再标记。
    """
    people = campus.people[80:86]
    _save(
        engine,
        *[
            _intent(
                p.id,
                created_at=NOW - timedelta(hours=12),
                deadline=NOW + timedelta(days=7),
            )
            for p in people
        ],
        now=NOW,
    )
    _clear(engine, now=NOW)

    with campus_connection(engine, SIM) as conn:
        unstable = conn.execute(
            sa.text(
                "SELECT count(*) FROM formation_proposals WHERE NOT stability_passed"
            )
        ).scalar_one()

    assert unstable == 0


def test_at_most_three_teams_are_offered(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """选择变多反而降低决策质量——实证上搜索上限 3→100 时福利显著下降。"""
    person = campus.people[90]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    _save(engine, intent, now=NOW)
    _clear(engine, now=NOW)

    with campus_connection(engine, SIM) as conn:
        stored = ProposalRepository(conn, SIM).list_for_intent(intent.id, now=NOW)

    assert len(stored) <= 3


def test_a_seed_says_why_it_came_to_you(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """投出去的每一颗种子都要说得出为什么投给他。

    **不给分数，不给相似度。** "他会剪辑，而你缺剪辑"是用户能判断的话，
    0.71 不是。说不出来就说不出来——编一条理由比不给理由伤害大。
    """
    person = campus.people[100]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    _save(engine, intent, now=NOW)
    _clear(engine, now=NOW)

    with campus_connection(engine, SIM) as conn:
        rows = conn.execute(
            sa.text("SELECT why FROM seed_deliveries WHERE intent_id = :i"),
            {"i": intent.id},
        ).all()

    assert rows, "一颗都没投出去"
    for row in rows:
        assert row.why, "投给他却说不出为什么"
        joined = "".join(row.why)
        assert "%" not in joined and "分" not in joined, joined


def test_proposals_stay_inside_their_tenant(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """另一个校园读不到这批提案。"""
    person = campus.people[110]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    _save(engine, intent, now=NOW)
    _clear(engine, now=NOW)

    with campus_connection(engine, "demo-campus") as conn:
        leaked = ProposalRepository(conn, "demo-campus").list_for_intent(
            intent.id, now=NOW
        )

    assert leaked == []


def test_a_seed_lands_answerable(engine: Engine, campus) -> None:  # type: ignore[no-untyped-def]
    """投到的那一刻它就是可以答的。

    投递制下这一条比提案时代简单得多：一条投递记录本身就是"可以答"，
    不需要另一侧再去把待答复开好。**少一个必须记得接上的地方，
    就少一个会断的地方。**
    """
    person = campus.people[120]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    _save(engine, intent, now=NOW)
    report = _clear(engine, now=NOW)
    assert report.proposed > 0, "这个用例需要真的投出去"

    with campus_connection(engine, SIM) as conn:
        states = conn.execute(
            sa.text("SELECT state FROM seed_deliveries WHERE intent_id = :i"),
            {"i": intent.id},
        ).all()

    assert states
    assert all(r.state == "delivered" for r in states)


def test_an_intent_without_a_deadline_still_gets_delivered(
    engine: Engine, campus
) -> None:  # type: ignore[no-untyped-def]
    """没写截止期的需求照样投得出去。

    这里原来拿 `EPOCH`（窗口对齐用的固定基准）当"现在"算兜底截止期，
    于是产出的东西一生成就过期——日志显示一切正常，而用户那一屏永远是空的。
    **静默是最坏的部分。**
    """
    person = campus.people[130]
    intent = _intent(
        person.id,
        created_at=NOW - timedelta(hours=12),
        deadline=NOW + timedelta(days=7),
    )
    intent = replace(intent, content=replace(intent.content, time_window=None))
    _save(engine, intent, now=NOW)
    _clear(engine, now=NOW)

    assert _delivered(engine, intent.id), "没写截止期就一颗都投不出去"


