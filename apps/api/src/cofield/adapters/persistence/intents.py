"""意图信号仓储。

领域对象与行之间的转换只在这里。注意 `list_matchable`——它是撮合漏斗
第一段的入口，过期判断在 SQL 里做而不是取回来再过滤，因为候选池可能是
整个校园。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.domain.model.intent import (
    IntentContent,
    IntentSignal,
    IntentState,
    TeamSize,
    TimeWindow,
)
from cofield.domain.ports.clock import Clock

from .schema import intent_signals


def _to_domain(row: Row[tuple[object, ...]]) -> IntentSignal:
    window = (
        TimeWindow(earliest=row.earliest, deadline=row.deadline)
        if row.earliest is not None and row.deadline is not None
        else None
    )
    size = (
        TeamSize(minimum=row.team_min, maximum=row.team_max)
        if row.team_min is not None and row.team_max is not None
        else None
    )
    return IntentSignal(
        id=row.id,
        principal_id=row.principal_id,
        state=IntentState(row.state),
        raw_expression=row.raw_expression,
        content=IntentContent(
            goal=row.goal,
            offers=tuple(row.offers),
            needs=tuple(row.needs),
            time_window=window,
            location_scope=row.location_scope,
            team_size=size,
            boundaries=tuple(row.boundaries),
            open_questions=tuple(row.open_questions),
            uncertain_fields=frozenset(row.uncertain_fields),
        ),
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _to_row(signal: IntentSignal, campus_id: str) -> dict[str, object]:
    c = signal.content
    return {
        "id": signal.id,
        "campus_id": campus_id,
        "principal_id": signal.principal_id,
        "state": signal.state.value,
        "raw_expression": signal.raw_expression,
        "goal": c.goal,
        "earliest": c.time_window.earliest if c.time_window else None,
        "deadline": c.time_window.deadline if c.time_window else None,
        "location_scope": c.location_scope,
        "team_min": c.team_size.minimum if c.team_size else None,
        "team_max": c.team_size.maximum if c.team_size else None,
        "offers": list(c.offers),
        "needs": list(c.needs),
        "boundaries": list(c.boundaries),
        "open_questions": list(c.open_questions),
        "uncertain_fields": sorted(c.uncertain_fields),
        "created_at": signal.created_at,
        "expires_at": signal.expires_at,
    }


class IntentRepository:
    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    def save(self, signal: IntentSignal) -> None:
        """新增或整体覆盖。意图是小对象，没必要做字段级更新。"""
        values = _to_row(signal, self._campus)
        stmt = pg_insert(intent_signals).values(**values)
        self._conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[intent_signals.c.id],
                set_={k: v for k, v in values.items() if k not in {"id", "campus_id"}},
            )
        )

    def get(self, intent_id: UUID) -> IntentSignal | None:
        row = self._conn.execute(
            sa.select(intent_signals).where(intent_signals.c.id == intent_id)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def list_for_principal(
        self, principal_id: UUID, *, states: set[IntentState] | None = None
    ) -> list[IntentSignal]:
        stmt = sa.select(intent_signals).where(
            intent_signals.c.principal_id == principal_id
        )
        if states:
            stmt = stmt.where(intent_signals.c.state.in_([s.value for s in states]))
        rows = self._conn.execute(
            stmt.order_by(intent_signals.c.created_at.desc())
        ).all()
        return [_to_domain(r) for r in rows]

    def list_matchable(self, *, now: datetime | None = None) -> list[IntentSignal]:
        """撮合漏斗第一段的入口。

        过期判断放在 SQL 里：候选池可能是整个校园，取回来再过滤是错的。
        """
        instant = now or self._clock.now()
        rows = self._conn.execute(
            sa.select(intent_signals)
            .where(intent_signals.c.state == IntentState.ACTIVE.value)
            .where(
                sa.or_(
                    intent_signals.c.expires_at.is_(None),
                    intent_signals.c.expires_at > instant,
                )
            )
            .order_by(intent_signals.c.deadline.asc().nulls_last())
        ).all()
        return [_to_domain(r) for r in rows]

    def expire_overdue(self, *, now: datetime | None = None) -> int:
        """把到期的活跃意图标记为过期。返回处理条数。"""
        instant = now or self._clock.now()
        result = self._conn.execute(
            sa.update(intent_signals)
            .where(intent_signals.c.state == IntentState.ACTIVE.value)
            .where(intent_signals.c.expires_at.is_not(None))
            .where(intent_signals.c.expires_at <= instant)
            .values(state=IntentState.EXPIRED.value)
        )
        return result.rowcount
