"""语义召回索引

结构化 schema 覆盖硬约束，覆盖不了表达。「想找个写朋克风格文案的」没有
任何表单字段装得下——这张表让原话参与匹配，而且不需要有人事先想到
「朋克风格」这个维度。

只索引**已授权用于匹配**的内容；撤销授权即删行。向量是派生物，
删库能从权威事实重建。

不建 HNSW 索引：召回发生在硬过滤**之后**，幸存者只有几百个，
对几百个向量做精确比较又快又准。建近似索引反而引入召回损失。

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"
DIMENSIONS = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "semantic_index",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("subject_kind", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Uuid, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIMENSIONS), nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_kind", "subject_id", name="uq_semantic_subject"),
    )
    op.create_index(
        "ix_semantic_campus_kind", "semantic_index", ["campus_id", "subject_kind"]
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON semantic_index TO {APP_ROLE}")
    op.execute("ALTER TABLE semantic_index ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE semantic_index FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY semantic_index_campus_isolation ON semantic_index
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS semantic_index_campus_isolation ON semantic_index")
    op.drop_table("semantic_index")
