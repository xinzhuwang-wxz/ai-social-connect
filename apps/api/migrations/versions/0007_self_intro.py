"""主体的一段自述

结构化字段覆盖硬约束，覆盖不了表达。这一列是**故意不结构化**的：
"想找个写朋克风格文案的"没有任何下拉框接得住，只能靠原话进语义索引。

可空——写不写由本人决定，不写不影响硬约束匹配。

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("principals", sa.Column("self_intro", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("principals", "self_intro")
