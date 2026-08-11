"""用户主体仓储。

行与领域对象之间的转换只在这一处发生。领域层拿到的永远是 `Principal`，
永远不是一行 `Row`——这样换掉持久化实现不会波及领域测试。
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Row

from cofield.domain.model.principal import CampusId, Principal
from cofield.domain.ports.clock import Clock

from .schema import principals


def _to_domain(row: Row[tuple[UUID, str, str, bool]]) -> Principal:
    return Principal(
        id=row.id,
        campus_id=CampusId(row.campus_id),
        display_name=row.display_name,
        is_synthetic=row.is_synthetic,
    )


class PrincipalRepository:
    """连接已绑定租户，因此这里没有一个方法接受 campus_id 参数。"""

    def __init__(self, conn: Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def add(self, principal: Principal) -> None:
        self._conn.execute(
            sa.insert(principals).values(
                id=principal.id,
                campus_id=principal.campus_id.value,
                display_name=principal.display_name,
                is_synthetic=principal.is_synthetic,
                created_at=self._clock.now(),
            )
        )

    def add_many(self, batch: Sequence[Principal]) -> None:
        if not batch:
            return
        created_at = self._clock.now()
        self._conn.execute(
            sa.insert(principals),
            [
                {
                    "id": p.id,
                    "campus_id": p.campus_id.value,
                    "display_name": p.display_name,
                    "is_synthetic": p.is_synthetic,
                    "created_at": created_at,
                }
                for p in batch
            ],
        )

    def get(self, principal_id: UUID) -> Principal | None:
        row = self._conn.execute(
            sa.select(principals).where(principals.c.id == principal_id)
        ).one_or_none()
        return _to_domain(row) if row is not None else None

    def list_all(self) -> list[Principal]:
        """列出当前租户下的全部主体。过滤由行级安全完成，不靠这里加 WHERE。"""
        rows = self._conn.execute(sa.select(principals).order_by(principals.c.id)).all()
        return [_to_domain(r) for r in rows]

    def count(self, *, is_synthetic: bool | None = None) -> int:
        stmt = sa.select(sa.func.count()).select_from(principals)
        if is_synthetic is not None:
            stmt = stmt.where(principals.c.is_synthetic == is_synthetic)
        return self._conn.execute(stmt).scalar_one()
