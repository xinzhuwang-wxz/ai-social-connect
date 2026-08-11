"""组织与行动机会

供给侧。冷启动策略是供给先行——没有人发布带席位的招募，撮合漏斗的
第一段就是空的。

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"
TABLES = ("organizations", "action_opportunities", "opportunity_seats")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_orgs_campus", "organizations", ["campus_id"])

    op.create_table(
        "action_opportunities",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("organization_id", sa.Uuid, nullable=False),
        sa.Column("kind_key", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("steward_id", sa.Uuid, nullable=False),
        sa.Column("deadline", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("location_scope", sa.Text),
        sa.Column("qualifications", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["steward_id"], ["principals.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_opps_campus_state", "action_opportunities", ["campus_id", "state"])
    op.create_index("ix_opps_campus_deadline", "action_opportunities", ["campus_id", "deadline"])

    op.create_table(
        "opportunity_seats",
        sa.Column("opportunity_id", sa.Uuid, primary_key=True),
        sa.Column("role", sa.Text, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column("filled", sa.Integer, nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["action_opportunities.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("capacity >= 1", name="ck_seat_capacity"),
        sa.CheckConstraint(
            "filled >= 0 AND filled <= capacity", name="ck_seat_filled_within_capacity"
        ),
    )

    for table in TABLES:
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
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_campus_isolation ON {table}")
        op.drop_table(table)
