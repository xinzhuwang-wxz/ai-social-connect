"""承诺、共同事件、共域、受限协商

M3 的全部表一次建好，让并行开发各自只碰自己的文件。

三条设计写在表结构里而不是只写在代码里：

1. `shared_events.proposal_id` 唯一 —— 一个提案最多变成一个事件，
   重复提交确认不该产生第二个。
2. `commitments (proposal_id, principal_id)` 唯一 —— 一个人对一个提案
   只能有一条答复，改主意是改这一行不是追加。
3. `spaces.event_id` 唯一 —— 共域是事件的空间，不是可以开好几个的群。

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"

NEW_TABLES = (
    "commitments",
    "shared_events",
    "event_members",
    "spaces",
    "space_items",
    "negotiation_tasks",
    "negotiation_messages",
)


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("proposal_id", sa.Uuid, nullable=False),
        sa.Column("principal_id", sa.Uuid, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="pending"),
        sa.Column("condition", sa.Text),
        sa.Column("decided_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("proposal_id", "principal_id", name="uq_commitment_person"),
    )
    op.create_index("ix_commitments_proposal", "commitments", ["campus_id", "proposal_id"])
    op.create_index(
        "ix_commitments_principal", "commitments", ["campus_id", "principal_id"]
    )

    op.create_table(
        "shared_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("proposal_id", sa.Uuid, nullable=False),
        sa.Column("action_kind", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("steward_id", sa.Uuid, nullable=False),
        sa.Column("formed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("deadline", sa.TIMESTAMP(timezone=True)),
        sa.Column("state", sa.Text, nullable=False, server_default="active"),
        sa.UniqueConstraint("proposal_id", name="uq_event_per_proposal"),
    )
    op.create_index("ix_events_campus_state", "shared_events", ["campus_id", "state"])

    op.create_table(
        "event_members",
        sa.Column("event_id", sa.Uuid, primary_key=True),
        sa.Column("principal_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("left_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_members_principal", "event_members", ["campus_id", "principal_id"])

    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("event_id", sa.Uuid, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "agent_enabled", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_space_per_event"),
    )
    op.create_index("ix_spaces_campus", "spaces", ["campus_id"])

    op.create_table(
        "space_items",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("space_id", sa.Uuid, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("assignee_id", sa.Uuid),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "drafted_by_agent", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("accepted_by", sa.Uuid),
        sa.Column("created_by", sa.Uuid, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("extras", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_items_space_kind", "space_items", ["campus_id", "space_id", "kind"]
    )

    op.create_table(
        "negotiation_tasks",
        sa.Column("task_id", sa.Text, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("context_id", sa.Text, nullable=False),
        sa.Column("proposal_id", sa.Uuid, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_negotiation_proposal", "negotiation_tasks", ["campus_id", "proposal_id"]
    )
    op.create_index(
        "ix_negotiation_context", "negotiation_tasks", ["campus_id", "context_id"]
    )

    op.create_table(
        "negotiation_messages",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("task_id", sa.Text, nullable=False),
        sa.Column("author_id", sa.Uuid, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("speaker_mode", sa.Text, nullable=False, server_default="self"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_messages_task",
        "negotiation_messages",
        ["campus_id", "task_id", "created_at"],
    )

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
