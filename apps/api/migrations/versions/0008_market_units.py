"""市场单元与成局提案

撮合按固定窗口清算，不是意图一提交就撮合。窗口长度由行动类别决定，
所以意图要记住自己属于哪个类别——它是真列不是 extras 里的键，
因为清算时要按它分组查询。

提案单独一张表，**不是**共同事件：提案只是"我们觉得这几个人能凑一队"，
事件要等全员真人确认才诞生。放在一起迟早有人拿提案当既成事实。

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY as PgArray

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.add_column("intent_signals", sa.Column("action_kind", sa.Text(), nullable=True))
    op.create_index(
        "ix_intents_unit", "intent_signals", ["campus_id", "action_kind", "state"]
    )

    op.create_table(
        "formation_proposals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("intent_id", sa.Uuid, nullable=False),
        sa.Column("action_kind", sa.Text),
        sa.Column("cleared_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("member_ids", PgArray(sa.Uuid), nullable=False),
        sa.Column("proof", sa.JSON, nullable=False),
        sa.Column("stability_passed", sa.Boolean, nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_proposals_intent", "formation_proposals", ["campus_id", "intent_id"]
    )
    op.create_index(
        "ix_proposals_cleared", "formation_proposals", ["campus_id", "cleared_at"]
    )

    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON formation_proposals TO {APP_ROLE}"
    )
    op.execute("ALTER TABLE formation_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE formation_proposals FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY formation_proposals_campus_isolation ON formation_proposals
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS formation_proposals_campus_isolation "
        "ON formation_proposals"
    )
    op.drop_table("formation_proposals")
    op.drop_index("ix_intents_unit", table_name="intent_signals")
    op.drop_column("intent_signals", "action_kind")
