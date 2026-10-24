"""sleep

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sleep_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("night", "nap", name="sleepkind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sleep_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sleep_sessions")),
    )
    with op.batch_alter_table("sleep_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_sleep_sessions_day"), ["day"], unique=False)
        batch_op.create_index(batch_op.f("ix_sleep_sessions_user_id"), ["user_id"], unique=False)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sleep_goal_min", sa.Integer(), server_default=sa.text("480"), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("sleep_goal_min")
    with op.batch_alter_table("sleep_sessions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sleep_sessions_user_id"))
        batch_op.drop_index(batch_op.f("ix_sleep_sessions_day"))
    op.drop_table("sleep_sessions")
