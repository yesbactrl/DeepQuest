"""goal color, icon and growth_only

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Копия services.goals.PALETTE на момент миграции: миграции не импортируют код приложения.
PALETTE = ("blue", "orange", "green", "amber", "pink", "forest", "violet", "red")


def upgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("color", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("icon", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("growth_only", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )

    # Цели, заведённые раньше, получают цвета палитры по порядку — как было на графиках.
    bind = op.get_bind()
    roots = bind.execute(
        sa.text("SELECT id, user_id FROM goals WHERE parent_id IS NULL ORDER BY user_id, id")
    ).all()
    rank: dict[int, int] = {}
    for goal_id, user_id in roots:
        index = rank.get(user_id, 0)
        rank[user_id] = index + 1
        bind.execute(
            sa.text("UPDATE goals SET color = :color WHERE id = :id"),
            {"color": PALETTE[index % len(PALETTE)], "id": goal_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_column("growth_only")
        batch_op.drop_column("icon")
        batch_op.drop_column("color")
