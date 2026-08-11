"""信封与同意记录仓储。

同意记录**只追加**：这里没有 update 方法，撤销靠写一条新的 withdrawn 事件
覆盖整行的 events 数组，原有的 given 事件不被抹掉。
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.domain.model.consent import (
    Audience,
    ConsentEvent,
    ConsentEventKind,
    ConsentRecord,
    EnvelopeState,
    FieldGrant,
    MatchEnvelope,
    Purpose,
)
from cofield.domain.ports.clock import Clock

from .schema import consent_records, match_envelopes


def _envelope(row: Row[tuple[object, ...]]) -> MatchEnvelope:
    grants = cast(dict[str, Any], row.grants)
    return MatchEnvelope(
        id=row.id,
        principal_id=row.principal_id,
        intent_id=row.intent_id,
        grants=tuple(
            FieldGrant(
                field_name=name,
                audience=Audience(spec["audience"]),
                purposes=frozenset(Purpose(p) for p in spec["purposes"]),
            )
            for name, spec in sorted(grants.items())
        ),
        created_at=row.created_at,
        expires_at=row.expires_at,
        state=EnvelopeState(row.state),
        cited_facet_ids=tuple(row.cited_facet_ids),
    )


class EnvelopeRepository:
    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    def save(self, envelope: MatchEnvelope) -> None:
        values: dict[str, Any] = {
            "id": envelope.id,
            "campus_id": self._campus,
            "principal_id": envelope.principal_id,
            "intent_id": envelope.intent_id,
            "grants": {
                g.field_name: {
                    "audience": g.audience.value,
                    "purposes": sorted(p.value for p in g.purposes),
                }
                for g in envelope.grants
            },
            "cited_facet_ids": list(envelope.cited_facet_ids),
            "state": envelope.state.value,
            "created_at": envelope.created_at,
            "expires_at": envelope.expires_at,
        }
        stmt = pg_insert(match_envelopes).values(**values)
        self._conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[match_envelopes.c.id],
                set_={
                    k: v
                    for k, v in values.items()
                    if k not in {"id", "campus_id", "created_at"}
                },
            )
        )

    def for_intent(self, intent_id: UUID) -> MatchEnvelope | None:
        row = self._conn.execute(
            sa.select(match_envelopes).where(match_envelopes.c.intent_id == intent_id)
        ).one_or_none()
        return _envelope(row) if row is not None else None

    def get(self, envelope_id: UUID) -> MatchEnvelope | None:
        row = self._conn.execute(
            sa.select(match_envelopes).where(match_envelopes.c.id == envelope_id)
        ).one_or_none()
        return _envelope(row) if row is not None else None

    def list_active(self, principal_id: UUID) -> list[MatchEnvelope]:
        """「谁能看到我」那一屏的数据源。只列还在生效的。"""
        rows = self._conn.execute(
            sa.select(match_envelopes)
            .where(match_envelopes.c.principal_id == principal_id)
            .where(match_envelopes.c.state == EnvelopeState.ACTIVE.value)
            .where(match_envelopes.c.expires_at > self._clock.now())
            .order_by(match_envelopes.c.created_at.desc())
        ).all()
        return [_envelope(r) for r in rows]


class ConsentRepository:
    """同意记录。只追加，不修改。"""

    def __init__(self, conn: Connection, clock: Clock, campus_id: str) -> None:
        self._conn = conn
        self._clock = clock
        self._campus = campus_id

    def append(self, record: ConsentRecord) -> None:
        self._conn.execute(
            pg_insert(consent_records)
            .values(
                record_id=record.record_id,
                campus_id=self._campus,
                pii_principal_id=record.pii_principal_id,
                pii_controller=record.pii_controller,
                schema_version=record.schema_version,
                notice_reference=record.notice_reference,
                purposes=[p.value for p in record.purposes],
                pii_categories=list(record.pii_categories),
                audience=record.audience.value,
                retention_until=record.retention_until,
                events=[
                    {"kind": e.kind.value, "occurred_at": e.occurred_at.isoformat()}
                    for e in record.events
                ],
                created_at=record.created_at,
            )
            .on_conflict_do_update(
                index_elements=[consent_records.c.record_id],
                # 只有 events 会增长，其余字段是记录成立那一刻的事实。
                set_={
                    "events": [
                        {"kind": e.kind.value, "occurred_at": e.occurred_at.isoformat()}
                        for e in record.events
                    ]
                },
            )
        )

    def get(self, record_id: UUID) -> ConsentRecord | None:
        row = self._conn.execute(
            sa.select(consent_records).where(consent_records.c.record_id == record_id)
        ).one_or_none()
        return _consent(row) if row is not None else None

    def list_for_principal(self, principal_id: UUID) -> list[ConsentRecord]:
        """数据导出用。导出的是完整记录，不做简化。"""
        rows = self._conn.execute(
            sa.select(consent_records)
            .where(consent_records.c.pii_principal_id == principal_id)
            .order_by(consent_records.c.created_at.desc())
        ).all()
        return [_consent(r) for r in rows]


def _consent(row: Row[tuple[object, ...]]) -> ConsentRecord:
    from datetime import datetime

    events = cast(list[dict[str, str]], row.events)
    return ConsentRecord(
        record_id=row.record_id,
        created_at=row.created_at,
        pii_principal_id=row.pii_principal_id,
        schema_version=row.schema_version,
        pii_controller=row.pii_controller,
        notice_reference=row.notice_reference,
        purposes=tuple(Purpose(p) for p in row.purposes),
        pii_categories=tuple(row.pii_categories),
        audience=Audience(row.audience),
        retention_until=row.retention_until,
        events=tuple(
            ConsentEvent(
                kind=ConsentEventKind(e["kind"]),
                occurred_at=datetime.fromisoformat(e["occurred_at"]),
            )
            for e in events
        ),
    )
