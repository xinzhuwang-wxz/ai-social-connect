"""换嵌入模型：384 → 1024 维

三个本地模型在**真实任务上**实测之后换的，不是按名气换的。任务是
「想找个写朋克风格文案的」，从 499 个会写文案的人里把文风野的捞到前面
（基线 7.0%）：

    bge-m3                    1024 维   top-20 命中 45%   6.4 倍富集
    all-minilm                 384 维   top-20 命中 25%   3.6 倍
    paraphrase-multilingual    768 维   top-20 命中 10%   1.4 倍

**直接清空重建，不做数据迁移。** 向量是派生物——不同模型的向量本来就
不可比，硬转过去只会得到一堆看起来有效、实际乱指的数字。权威事实
（`principals.self_intro`、`intent_signals.raw_expression`）一个字没动，
重新索引就回来了。

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 先清空再改类型：pgvector 不允许在有数据时改维度，而这些数据
    # 本来就该被丢掉——它们是用另一个模型算的。
    op.execute("TRUNCATE semantic_index")
    op.execute("ALTER TABLE semantic_index ALTER COLUMN embedding TYPE vector(1024)")


def downgrade() -> None:
    op.execute("TRUNCATE semantic_index")
    op.execute("ALTER TABLE semantic_index ALTER COLUMN embedding TYPE vector(384)")
