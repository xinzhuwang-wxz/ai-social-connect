"""意图信号

硬约束字段提升为真列：撮合漏斗的第一段是 SQL 过滤，它们要能被索引。
可扩展部分放 `extras`，这样新增行动类别不需要改表结构。

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "intent_signals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Uuid, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("raw_expression", sa.Text, nullable=False),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("earliest", sa.TIMESTAMP(timezone=True)),
        sa.Column("deadline", sa.TIMESTAMP(timezone=True)),
        sa.Column("location_scope", sa.Text),
        sa.Column("team_min", sa.Integer),
        sa.Column("team_max", sa.Integer),
        sa.Column("offers", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("needs", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("boundaries", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("open_questions", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("uncertain_fields", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("extras", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True)),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "team_min IS NULL OR team_min >= 2",
            name="ck_intent_team_min_at_least_two",
        ),
        sa.CheckConstraint(
            "team_max IS NULL OR team_min IS NULL OR team_max >= team_min",
            name="ck_intent_team_range",
        ),
        sa.CheckConstraint(
            "deadline IS NULL OR earliest IS NULL OR deadline >= earliest",
            name="ck_intent_time_window",
        ),
    )
    op.create_index("ix_intents_campus_state", "intent_signals", ["campus_id", "state"])
    op.create_index("ix_intents_campus_deadline", "intent_signals", ["campus_id", "deadline"])
    op.create_index("ix_intents_principal", "intent_signals", ["campus_id", "principal_id"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON intent_signals TO {APP_ROLE}")
    op.execute("ALTER TABLE intent_signals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE intent_signals FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY intent_signals_campus_isolation ON intent_signals
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS intent_signals_campus_isolation ON intent_signals")
    op.drop_table("intent_signals")
