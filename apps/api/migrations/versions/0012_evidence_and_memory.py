"""行动证据与记忆切面

闭环在这里合上：一次共同行动留下证据 → 抽成记忆切面草稿 → **本人逐项确认**
→ 确认过的切面能被下一次成局证明引用。

三条设计写在表里：

1. `state` 只有 `confirmed` 能被引用。`draft` 是系统的猜测，
   `revoked` 是本人收回过的话。
2. `evidence_ids` 让每条记忆指得回它的来源。说不出来源的记忆，
   本人无从判断该不该留着它。
3. `evidence` 只存事实不存评价。一旦开始存"这次谁表现好"，
   它就变成打分系统，而打分系统会让人不敢参加自己不擅长的事。

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY as PgArray

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"
NEW_TABLES = ("evidence", "memory_facets")


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("event_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("uri", sa.Text),
        sa.Column("uploaded_by", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_event", "evidence", ["campus_id", "event_id"])

    op.create_table(
        "memory_facets",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Uuid, nullable=False),
        sa.Column("event_id", sa.Uuid),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column(
            "evidence_ids", PgArray(sa.Uuid), nullable=False, server_default="{}"
        ),
        sa.Column("state", sa.Text, nullable=False, server_default="draft"),
        sa.Column(
            "drafted_by_agent", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_facets_principal_state",
        "memory_facets",
        ["campus_id", "principal_id", "state"],
    )
    op.create_index("ix_facets_event", "memory_facets", ["campus_id", "event_id"])

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_campus_isolation ON {table}
            TO {APP_ROLE}
            USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
            WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
            """
        )


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_campus_isolation ON {table}")
        op.drop_table(table)
