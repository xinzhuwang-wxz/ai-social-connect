"""principals 表与行级租户隔离

租户隔离用 Postgres 行级安全，而不是"每个查询记得加 WHERE campus_id"。
理由：忘记加 WHERE 是一次代码审查疏漏；忘记开 RLS 是一次迁移评审疏漏，
后者次数少得多，也更容易被测试逮住。

`FORCE ROW LEVEL SECURITY` 是关键——不加的话表的属主会绕过策略，
而在开发环境里应用连的往往就是属主，隔离测试会变成一场表演。

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CAMPUS_SETTING = "app.current_campus"

#: 应用角色。**超级用户和表属主都会绕过 RLS**，所以业务查询必须以一个
#: 既非超级用户、又非属主、且 NOBYPASSRLS 的角色执行。它是 NOLOGIN 的——
#: 我们不为它管理密码，而是在事务内 `SET LOCAL ROLE` 切过去。
APP_ROLE = "cofield_app"


def upgrade() -> None:
    op.create_table(
        "principals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("campus_id", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("is_synthetic", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_principals_campus", "principals", ["campus_id"])
    op.create_index(
        "ix_principals_campus_synthetic", "principals", ["campus_id", "is_synthetic"]
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS
                    NOCREATEDB NOCREATEROLE NOINHERIT;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON principals TO {APP_ROLE}")
    op.execute(f"GRANT {APP_ROLE} TO CURRENT_USER")

    op.execute("ALTER TABLE principals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE principals FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY principals_campus_isolation ON principals
        TO {APP_ROLE}
        USING (campus_id = current_setting('{CAMPUS_SETTING}', true))
        WITH CHECK (campus_id = current_setting('{CAMPUS_SETTING}', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS principals_campus_isolation ON principals")
    op.execute(f"REVOKE ALL ON principals FROM {APP_ROLE}")
    op.drop_index("ix_principals_campus_synthetic", table_name="principals")
    op.drop_index("ix_principals_campus", table_name="principals")
    op.drop_table("principals")
