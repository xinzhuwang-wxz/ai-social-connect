"""租户隔离：行级安全真的生效，不是靠每个查询记得加 WHERE。

这些用例跑在真 PostgreSQL 18 上，跑的是真迁移。它们要证明的是——
即便一个查询完全没提 campus_id，也读不到别的租户的行。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.clock import FrozenClock
from cofield.adapters.persistence.engine import app_connection, campus_connection
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.domain.model.principal import CampusId, Principal

REAL = "demo-campus"
SIM = "simulation"


def person(campus: str, name: str, *, synthetic: bool = False) -> Principal:
    return Principal(
        id=uuid4(),
        campus_id=CampusId(campus),
        display_name=name,
        is_synthetic=synthetic,
    )


def test_a_campus_cannot_see_another_campus(engine: Engine, clock: FrozenClock) -> None:
    with campus_connection(engine, REAL) as conn:
        PrincipalRepository(conn, clock).add(person(REAL, "林知遥"))
    with campus_connection(engine, SIM) as conn:
        PrincipalRepository(conn, clock).add(person(SIM, "合成-0001", synthetic=True))

    with campus_connection(engine, REAL) as conn:
        names = [p.display_name for p in PrincipalRepository(conn, clock).list_all()]
    assert names == ["林知遥"]

    with campus_connection(engine, SIM) as conn:
        names = [p.display_name for p in PrincipalRepository(conn, clock).list_all()]
    assert names == ["合成-0001"]


def test_lookup_by_id_across_tenants_returns_nothing(
    engine: Engine, clock: FrozenClock
) -> None:
    """知道对方的主键也读不到——隔离不依赖 ID 不可猜。"""
    stranger = person(SIM, "合成-0002", synthetic=True)
    with campus_connection(engine, SIM) as conn:
        PrincipalRepository(conn, clock).add(stranger)

    with campus_connection(engine, REAL) as conn:
        assert PrincipalRepository(conn, clock).get(stranger.id) is None


def test_writing_into_another_campus_is_rejected(
    engine: Engine, clock: FrozenClock
) -> None:
    """策略带 WITH CHECK，所以越租户写入会被数据库直接拒绝。"""
    with pytest.raises(sa.exc.ProgrammingError, match="row-level security"):
        with campus_connection(engine, REAL) as conn:
            PrincipalRepository(conn, clock).add(person(SIM, "越界写入"))


def test_no_tenant_context_means_no_rows(engine: Engine, clock: FrozenClock) -> None:
    """没设租户变量时策略求值为 NULL，读不到任何行——默认拒绝而不是默认放行。"""
    with campus_connection(engine, REAL) as conn:
        PrincipalRepository(conn, clock).add(person(REAL, "林知遥"))

    with app_connection(engine) as conn:
        assert PrincipalRepository(conn, clock).count() == 0


def test_empty_campus_id_is_refused_before_reaching_the_database(engine: Engine) -> None:
    with pytest.raises(ValueError, match="campus_id 不能为空"):
        with campus_connection(engine, "  "):
            pass


def test_synthetic_and_real_are_separated_by_tenant(
    engine: Engine, clock: FrozenClock
) -> None:
    """合成主体只存在于仿真租户里，真实租户里一个都看不到。

    这是「合成主体不与真人同局」的第一道防线：他们根本不在同一个可见集合中。
    第二道防线是领域规则 `formation.eligibility`。
    """
    with campus_connection(engine, SIM) as conn:
        repo = PrincipalRepository(conn, clock)
        repo.add_many([person(SIM, f"合成-{i:04d}", synthetic=True) for i in range(50)])
    with campus_connection(engine, REAL) as conn:
        PrincipalRepository(conn, clock).add(person(REAL, "陈牧"))

    with campus_connection(engine, REAL) as conn:
        repo = PrincipalRepository(conn, clock)
        assert repo.count() == 1
        assert repo.count(is_synthetic=True) == 0

    with campus_connection(engine, SIM) as conn:
        assert PrincipalRepository(conn, clock).count(is_synthetic=True) == 50
