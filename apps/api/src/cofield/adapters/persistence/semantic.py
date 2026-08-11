"""语义索引的写入侧。

**只索引已授权用于匹配的内容。** 向量是派生物——撤销授权就删行，
删库能从权威事实重建。Postgres 仍是唯一权威，这张表不是第二数据源。

不建 HNSW/IVFFlat 索引是**故意的**：召回发生在硬过滤之后，幸存者通常
只有几百到几千个，对这个量级做精确比较又快又准。近似索引在这里买不到
速度，只会引入召回损失。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cofield.adapters.persistence.schema import semantic_index
from cofield.domain.ports.embedder import Embedder

#: 被索引的对象类型。人和意图分开——同一个人的自述和他这次说的话
#: 是两件事，混在一起会让"他一贯什么风格"和"他这次想干嘛"互相污染。
PRINCIPAL = "principal"
INTENT = "intent"

BATCH = 256


@dataclass(frozen=True, slots=True)
class IndexableText:
    """一段待索引的文本，连同它属于谁。"""

    subject_id: UUID
    text: str


class SemanticIndexWriter:
    def __init__(self, conn: Connection, embedder: Embedder) -> None:
        self._conn = conn
        self._embedder = embedder

    def index(
        self,
        items: Sequence[IndexableText],
        *,
        subject_kind: str,
        campus_id: str,
        now: datetime,
        model: str = "all-minilm",
    ) -> int:
        """写入或更新。同一个对象重复索引就覆盖，不留历史版本——
        历史在权威事实那边，这里只是当前状态的投影。

        空文本直接跳过：没写自述的人不该在索引里占一行，
        否则"没写"会被当成一个可比较的语义位置。
        """
        usable = [i for i in items if i.text.strip()]
        if not usable:
            return 0

        written = 0
        for start in range(0, len(usable), BATCH):
            chunk = usable[start : start + BATCH]
            vectors = self._embedder.embed([i.text for i in chunk])
            rows = [
                {
                    "id": uuid4(),
                    "campus_id": campus_id,
                    "subject_kind": subject_kind,
                    "subject_id": item.subject_id,
                    "text": item.text,
                    "embedding": vector,
                    "model": model,
                    "created_at": now,
                }
                for item, vector in zip(chunk, vectors, strict=True)
            ]
            stmt = pg_insert(semantic_index).values(rows)
            self._conn.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_semantic_subject",
                    set_={
                        "text": stmt.excluded.text,
                        "embedding": stmt.excluded.embedding,
                        "model": stmt.excluded.model,
                        "created_at": stmt.excluded.created_at,
                    },
                )
            )
            written += len(rows)
        return written

    def forget(self, *, subject_kind: str, subject_id: UUID) -> int:
        """撤销授权即删行。

        这不是"清缓存"——用户撤回了露出，他的原话就不该再参与任何人的匹配。
        """
        result = self._conn.execute(
            sa.delete(semantic_index).where(
                semantic_index.c.subject_kind == subject_kind,
                semantic_index.c.subject_id == subject_id,
            )
        )
        return result.rowcount
