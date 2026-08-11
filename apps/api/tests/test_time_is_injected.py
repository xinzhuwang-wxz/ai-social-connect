"""时间是注入的，不是读来的。

两件事在这里被钉死：

1. 推进仿真时钟能被观察到——写入的时间戳跟着变，说明持久化层用的确实是
   注入的时钟而不是偷偷调了 `now()`。
2. 整个测试套件里没有 sleep。时间相关的行为靠推进时钟来测，
   一旦有人用 sleep，这条会失败。
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.clock import SimulatedClock
from cofield.adapters.persistence.engine import campus_connection
from cofield.adapters.persistence.principals import PrincipalRepository
from cofield.adapters.persistence.schema import principals
from cofield.domain.model.principal import CampusId, Principal

START = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
CAMPUS = "demo-campus"
TESTS_DIR = Path(__file__).parent


def person(name: str) -> Principal:
    return Principal(id=uuid4(), campus_id=CampusId(CAMPUS), display_name=name)


def test_advancing_the_clock_changes_what_gets_persisted(engine: Engine) -> None:
    """两周的间隔在测试里是一次 advance，不是十四天的等待。"""
    clock = SimulatedClock(START)

    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, clock).add(person("林知遥"))

    clock.advance(timedelta(days=14))

    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, clock).add(person("陈牧"))

    with campus_connection(engine, CAMPUS) as conn:
        rows = conn.execute(
            sa.select(principals.c.display_name, principals.c.created_at).order_by(
                principals.c.created_at
            )
        ).all()

    assert [r.display_name for r in rows] == ["林知遥", "陈牧"]
    assert rows[1].created_at - rows[0].created_at == timedelta(days=14)


def test_the_repository_does_not_read_the_wall_clock(engine: Engine) -> None:
    """注入一个停在过去的时钟，写出来的时间戳就该在过去。

    如果哪天有人在仓储里写了 `datetime.now()`，这条会失败——领域纯度检查
    只覆盖 domain/，适配器层靠这类行为测试兜住。
    """
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    clock = SimulatedClock(long_ago)

    with campus_connection(engine, CAMPUS) as conn:
        PrincipalRepository(conn, clock).add(person("时间旅行者"))

    with campus_connection(engine, CAMPUS) as conn:
        created_at = conn.execute(sa.select(principals.c.created_at)).scalar_one()

    assert created_at == long_ago


def test_no_test_sleeps() -> None:
    """时间行为靠推进时钟测。用 sleep 的测试既慢又会在 CI 上闪烁。"""
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if name == "sleep":
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, f"测试里不允许 sleep，改用 SimulatedClock.advance：{offenders}"
