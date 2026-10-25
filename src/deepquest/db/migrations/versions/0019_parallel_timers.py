"""parallel timers: one running entry per task, not per user

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNNING = sa.text("ended_at IS NULL")


def upgrade() -> None:
    with op.batch_alter_table("time_entries", schema=None) as batch_op:
        batch_op.drop_index("uq_time_entries_running", sqlite_where=RUNNING)
        batch_op.create_index(
            "uq_time_entries_running_task", ["task_id"], unique=True, sqlite_where=RUNNING
        )


def downgrade() -> None:
    # Обратно — один таймер на пользователя: лишние идущие отрезки закрываем.
    op.execute(
        "UPDATE time_entries SET ended_at = started_at, stop_reason = 'switched' "
        "WHERE ended_at IS NULL AND id NOT IN ("
        "SELECT MAX(id) FROM time_entries WHERE ended_at IS NULL GROUP BY user_id)"
    )
    with op.batch_alter_table("time_entries", schema=None) as batch_op:
        batch_op.drop_index("uq_time_entries_running_task", sqlite_where=RUNNING)
        batch_op.create_index(
            "uq_time_entries_running", ["user_id"], unique=True, sqlite_where=RUNNING
        )
