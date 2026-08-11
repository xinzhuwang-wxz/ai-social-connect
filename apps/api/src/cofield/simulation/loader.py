"""把合成人口装进库。

用属主连接绕过 RLS 批量写——装载是运维动作，不是业务动作。
装完之后所有读取仍然走应用角色，隔离照常生效。
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Engine

from cofield.adapters.persistence.engine import owner_connection
from cofield.adapters.persistence.schema import principals
from cofield.simulation.population import Population

BATCH = 2000


def load_principals(
    engine: Engine, population: Population, *, campus_id: str, now: datetime
) -> int:
    """写入合成主体。全部标 is_synthetic —— 它们永不与真人同局。"""
    rows = [
        {
            "id": p.id,
            "campus_id": campus_id,
            "display_name": p.display_name,
            "is_synthetic": True,
            "created_at": now,
            "major": p.major,
            "year": p.year,
            "zone": p.zone,
            "skills": list(p.skills),
            "availability": p.availability,
            "self_intro": p.self_intro,
        }
        for p in population.people
    ]
    with owner_connection(engine) as conn:
        for start in range(0, len(rows), BATCH):
            conn.execute(sa.insert(principals), rows[start : start + BATCH])
    return len(rows)
