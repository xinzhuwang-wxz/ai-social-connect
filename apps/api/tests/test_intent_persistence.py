"""意图的持久化与撮合入口。

这里要证明的不是"能存能取"，而是三件事：草稿存得下但取不进撮合池、
过期判断发生在 SQL 里、以及租户之间互相看不见。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.adapters.persistence.engine import campus_connection
from cofield.adapters.persistence.intents import IntentRepository
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.domain.model.principal import CampusId, Principal

NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
REAL = "demo-campus"
SIM = "simulation"
TTL = timedelta(days=3)


def _seed_principal(engine: Engine, campus: str, *, synthetic: bool = False) -> Principal:
    person = Principal(
        id=uuid4(),
        campus_id=CampusId(campus),
        display_name="合成" if synthetic else "真人",
        is_synthetic=synthetic,
    )
    with campus_connection(engine, campus) as conn:
        PrincipalRepository(conn, SimulatedClock(NOW)).add(person)
    return person


def _intent(owner: Principal, *, deadline: datetime | None = None) -> IntentSignal:
    window = TimeWindow(earliest=NOW, deadline=deadline) if deadline else None
    return IntentSignal(
        id=uuid4(),
        principal_id=owner.id,
        state=IntentState.DRAFT,
        raw_expression="想拍个流浪猫短片，周五前完成",
        content=IntentContent(
            goal="周五前完成 60 秒短片",
            offers=("脚本",),
            needs=("拍摄", "剪辑"),
            time_window=window,
            location_scope="东校区",
            team_size=TeamSize(3, 4),
            open_questions=("是否公开发布",),
            uncertain_fields=frozenset({"team_size"}),
        ),
        created_at=NOW,
    )


def test_content_survives_a_round_trip(engine: Engine) -> None:
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    original = _intent(owner, deadline=NOW + timedelta(days=2))

    with campus_connection(engine, REAL) as conn:
        IntentRepository(conn, clock, REAL).save(original)
    with campus_connection(engine, REAL) as conn:
        loaded = IntentRepository(conn, clock, REAL).get(original.id)

    assert loaded == original


def test_a_draft_is_stored_but_stays_out_of_the_matching_pool(engine: Engine) -> None:
    """那道门在数据层也成立：草稿存得下，但 `list_matchable` 取不到。"""
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    draft = _intent(owner, deadline=NOW + timedelta(days=2))

    with campus_connection(engine, REAL) as conn:
        repo = IntentRepository(conn, clock, REAL)
        repo.save(draft)
        assert repo.get(draft.id) is not None
        assert repo.list_matchable() == []


def test_confirming_puts_it_in_the_pool(engine: Engine) -> None:
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    active = _intent(owner, deadline=NOW + timedelta(days=2)).confirm(now=NOW, ttl=TTL)

    with campus_connection(engine, REAL) as conn:
        repo = IntentRepository(conn, clock, REAL)
        repo.save(active)
        assert [i.id for i in repo.list_matchable()] == [active.id]


def test_the_pool_shrinks_as_the_clock_advances(engine: Engine) -> None:
    """过期发生在时间推进时，不需要任何后台任务先跑过。"""
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    active = _intent(owner, deadline=NOW + timedelta(days=2)).confirm(now=NOW, ttl=TTL)

    with campus_connection(engine, REAL) as conn:
        IntentRepository(conn, clock, REAL).save(active)

    clock.advance(timedelta(days=3))

    with campus_connection(engine, REAL) as conn:
        assert IntentRepository(conn, clock, REAL).list_matchable() == []




def test_saving_twice_updates_rather_than_duplicates(engine: Engine) -> None:
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    draft = _intent(owner, deadline=NOW + timedelta(days=2))

    with campus_connection(engine, REAL) as conn:
        repo = IntentRepository(conn, clock, REAL)
        repo.save(draft)
        repo.save(draft.confirm(now=NOW, ttl=TTL))
        found = repo.list_for_principal(owner.id)

    assert len(found) == 1
    assert found[0].state is IntentState.ACTIVE


def test_intents_do_not_leak_across_campuses(engine: Engine) -> None:
    real_owner = _seed_principal(engine, REAL)
    sim_owner = _seed_principal(engine, SIM, synthetic=True)
    clock = SimulatedClock(NOW)

    for campus, owner in ((REAL, real_owner), (SIM, sim_owner)):
        with campus_connection(engine, campus) as conn:
            IntentRepository(conn, clock, campus).save(
                _intent(owner, deadline=NOW + timedelta(days=2)).confirm(
                    now=NOW, ttl=TTL
                )
            )

    with campus_connection(engine, REAL) as conn:
        pool = IntentRepository(conn, clock, REAL).list_matchable()
    assert [i.principal_id for i in pool] == [real_owner.id]


def test_the_pool_is_ordered_by_who_leaves_the_market_first(engine: Engine) -> None:
    """撮合窗口要先处理截止期临近的人，所以池子按 deadline 升序给出。"""
    owner = _seed_principal(engine, REAL)
    clock = SimulatedClock(NOW)
    later = _intent(owner, deadline=NOW + timedelta(days=5)).confirm(now=NOW, ttl=TTL)
    sooner = _intent(owner, deadline=NOW + timedelta(days=1)).confirm(now=NOW, ttl=TTL)

    with campus_connection(engine, REAL) as conn:
        repo = IntentRepository(conn, clock, REAL)
        repo.save(later)
        repo.save(sooner)
        pool = repo.list_matchable()

    assert [i.id for i in pool] == [sooner.id, later.id]
