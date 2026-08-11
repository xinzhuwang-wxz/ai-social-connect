"""匹配信封与同意记录

两张表分工不同：信封是**运行期用来过滤字段的对象**，会被撤销和过期；
同意记录是**可审计的事实**，只追加不修改，申诉与导出看它。

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"
APP_ROLE = "cofield_app"
TABLES = ("match_envelopes", "consent_records")


def upgrade() -> None:
    op.create_table(
        "match_envelopes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Uuid, nullable=False),
        sa.Column("intent_id", sa.Uuid, nullable=False),
        sa.Column("grants", sa.JSON, nullable=False),
        sa.Column("cited_facet_ids", sa.ARRAY(sa.Uuid), nullable=False, server_default="{}"),
        sa.Column("state", sa.Text, nullable=False, server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["intent_id"], ["intent_signals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("intent_id", name="uq_envelope_per_intent"),
    )
    op.create_index("ix_envelopes_intent", "match_envelopes", ["campus_id", "intent_id"])
    op.create_index("ix_envelopes_principal", "match_envelopes", ["campus_id", "principal_id"])

    op.create_table(
        "consent_records",
        sa.Column("record_id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("pii_principal_id", sa.Uuid, nullable=False),
        sa.Column("pii_controller", sa.Text, nullable=False),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("notice_reference", sa.Text, nullable=False),
        sa.Column("purposes", sa.ARRAY(sa.Text), nullable=False),
        sa.Column("pii_categories", sa.ARRAY(sa.Text), nullable=False),
        sa.Column("audience", sa.Text, nullable=False),
        sa.Column("retention_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pii_principal_id"], ["principals.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_consent_principal", "consent_records", ["campus_id", "pii_principal_id"]
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
