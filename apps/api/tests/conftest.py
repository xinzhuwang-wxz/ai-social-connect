"""测试基座：真 PostgreSQL 18，真迁移。

本项目不用手写 mock 或 stub 替代自己的任何一层。这里起的是真数据库、
跑的是真迁移——唯一被替换的是"人"（`is_synthetic`），不是任何一层技术。
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from cofield.adapters.clock import FrozenClock
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
        conn.execute(sa.text("TRUNCATE principals, intent_signals"))
