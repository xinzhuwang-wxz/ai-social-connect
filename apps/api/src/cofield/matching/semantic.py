"""语义召回：在硬过滤**之后**排序。

## 为什么顺序不能反

先召回后过滤有两个问题，一个是安全的，一个是效果的：

**侧信道。** 攻击者反复查询，从结果数量与时延差异就能反推出被隐藏的字段。
权限过滤必须发生在任何比较之前。

**高选择性下 post-filter 会崩。** 两万人过滤到几百是 1.5% 的选择性，
近似索引这时候召回一堆待会儿要被扔掉的行。而先过滤之后，对几百个向量
做**精确**比较成本微不足道——这正是 pgvector 最舒服的场景，也是我们
不建 HNSW 的原因。

所以这里的接口收的是一条**已经带上全部硬约束的 SELECT 语句**，
不是一串 id。过滤和比较在同一个查询里，顺序由 SQL 保证，不靠调用方自觉。

## 它排的是什么

结构化字段覆盖硬约束，覆盖不了表达。"想找个写朋克风格文案的"——
"写文案"是字段，"朋克"不是，而且没有人会事先想到该建一个"朋克"字段。
用户的原话一直被完整保留着，接上向量之后它才真正参与匹配。

命中要带上**原文**，不只带分数：成局证明里要能引用"他自己写的『文风比较冲』"，
引用一个 0.71 没有任何意义，用户也无从判断这个理由成不成立。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.sql import Select

from cofield.adapters.persistence.schema import semantic_index
from cofield.adapters.persistence.semantic import PRINCIPAL
from cofield.domain.ports.embedder import Embedder


@dataclass(frozen=True, slots=True)
class SemanticHit:
    subject_id: UUID
    #: 余弦相似度。**不给用户看**——它只用来排序，理由靠 `matched_text`。
    similarity: float
    #: 命中的原话。它本身就是已授权内容，所以可以直接进证明。
    matched_text: str


class SemanticRetriever:
    def __init__(self, conn: Connection, embedder: Embedder) -> None:
        self._conn = conn
        self._embedder = embedder

    def rank(
        self, query: str, filtered: Select[tuple[UUID]], *, keep: int = 200
    ) -> tuple[SemanticHit, ...]:
        """对**已通过硬过滤**的人按语义排序，取前 keep 个。

        `filtered` 必须是一条只选 id 的语句，且已经带上全部硬约束与权限条件。
        这里把它当子查询 JOIN 进来——过滤先于比较是 SQL 保证的，不是约定。

        `EmbeddingUnavailable` **不在这里吞掉**。降级要不要发生、降级到什么，
        是漏斗的决定；这一层假装没事会让降级变得不可观测。
        """
        if not query.strip():
            return ()

        vector = self._embedder.embed([query])[0]
        survivors = filtered.subquery()
        distance = semantic_index.c.embedding.cosine_distance(vector)

        rows = self._conn.execute(
            sa.select(
                semantic_index.c.subject_id,
                semantic_index.c.text,
                distance.label("distance"),
            )
            .select_from(
                survivors.join(
                    semantic_index,
                    semantic_index.c.subject_id == survivors.c.id,
                )
            )
            .where(semantic_index.c.subject_kind == PRINCIPAL)
            .order_by(distance)
            .limit(keep)
        ).all()

        return tuple(
            SemanticHit(
                subject_id=row.subject_id,
                similarity=1.0 - float(row.distance),
                matched_text=row.text,
            )
            for row in rows
        )
