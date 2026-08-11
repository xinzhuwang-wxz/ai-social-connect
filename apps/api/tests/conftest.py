"""测试基座：真 PostgreSQL 18，真迁移。

本项目不用手写 mock 或 stub 替代自己的任何一层。这里起的是真数据库、
跑的是真迁移——唯一被替换的是"人"（`is_synthetic`），不是任何一层技术。
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

from cofield.adapters.clock import FrozenClock, SimulatedClock
from cofield.adapters.persistence.engine import build_engine, owner_connection

REPO_API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 单元测试用的固定时刻。带时区——领域里不接受 naive datetime。
FIXED_NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def database_url() -> Generator[str, None, None]:
    """起一个真 PostgreSQL 18 容器。

    允许用 COFIELD_TEST_DATABASE_URL 指向一个已有实例（CI 里可能已有服务），
    但默认走容器，这样 `pytest` 开箱即用不需要先读文档。
    """
    existing = os.environ.get("COFIELD_TEST_DATABASE_URL")
    if existing:
        yield existing
        return

    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # 旧版 testcontainers
        from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def engine(database_url: str) -> Generator[Engine, None, None]:
    cfg = Config(os.path.join(REPO_API_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_API_ROOT, "migrations"))
    os.environ["COFIELD_DATABASE_URL"] = database_url
    command.upgrade(cfg, "head")

    eng = build_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(FIXED_NOW)


@pytest.fixture(autouse=True)
def _clean_tables(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """每个用例之间清表。

    只在真正用到 engine 的用例上生效——纯领域单元测试不该为此付出起容器的代价。
    """
    yield
    if "engine" not in request.fixturenames:
        return
    import sqlalchemy as sa

    eng: Engine = request.getfixturevalue("engine")
    # 跨 campus 清表是属主的活儿——策略按 campus 过滤，应用角色做不到也不该做到。
    with owner_connection(eng) as conn:
        conn.execute(
            sa.text(
                "TRUNCATE consent_records, match_envelopes, opportunity_seats, "
                "action_opportunities, organizations, intent_signals, principals"
            )
        )


# --- 端到端用例的共用装配 ---------------------------------------------------
# 四个测试文件曾各自定义过一份几乎相同的 client/me/seed。它们从来不会不一致，
# 但一致性是靠人记住的——挪到这里之后，改一次身份注入方式只改一处。

CAMPUS = "demo-campus"
SIM_CAMPUS = "simulation"


@pytest.fixture
def sim_clock() -> SimulatedClock:
    from cofield.adapters.clock import SimulatedClock as _Sim

    return _Sim(FIXED_NOW)


@pytest.fixture
def seed_principal(engine: Engine):  # type: ignore[no-untyped-def]
    """造一个主体。默认真人；`synthetic=True` 造合成主体。"""
    from uuid import uuid4

    from cofield.adapters.clock import SimulatedClock as _Sim
    from cofield.adapters.persistence.engine import campus_connection
    from cofield.adapters.persistence.principals import PrincipalRepository
    from cofield.domain.model.principal import CampusId, Principal

    def make(
        *, campus: str = CAMPUS, name: str = "林知遥", synthetic: bool = False
    ) -> Principal:
        person = Principal(
            id=uuid4(),
            campus_id=CampusId(campus),
            display_name=name,
            is_synthetic=synthetic,
        )
        with campus_connection(engine, campus) as conn:
            PrincipalRepository(conn, _Sim(FIXED_NOW)).add(person)
        return person

    return make


@pytest.fixture
def me(seed_principal):  # type: ignore[no-untyped-def]
    return seed_principal()


@pytest.fixture
def client(  # type: ignore[no-untyped-def]
    engine: Engine, me, sim_clock: SimulatedClock
) -> Generator[TestClient, None, None]:
    """带身份与租户的客户端，跑在可推进的时钟上。"""
    from fastapi.testclient import TestClient as _Client

    from cofield.http import deps
    from cofield.http.app import create_app

    app = create_app()
    app.state.clock = sim_clock
    app.dependency_overrides[deps.get_engine] = lambda: engine
    with _Client(app) as c:
        c.headers.update({"X-Principal-Id": str(me.id), "X-Campus-Id": CAMPUS})
        yield c
