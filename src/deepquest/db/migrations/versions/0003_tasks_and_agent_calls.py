"""tasks and agent calls

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-20 02:54:32.737285

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_calls_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_calls")),
    )
    with op.batch_alter_table("agent_calls", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_agent_calls_user_id"), ["user_id"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("estimate_min", sa.Integer(), nullable=True),
        sa.Column("value_mult", sa.Double(), nullable=True),
        sa.Column("mult_reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "clarifying",
                "draft",
                "open",
                "running",
                "awaiting_report",
                "done",
                "rejected",
                "cancelled",
                name="taskstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("clarify_question", sa.Text(), nullable=True),
        sa.Column("clarify_answer", sa.Text(), nullable=True),
        sa.Column("agent_call_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_call_id"],
            ["agent_calls.id"],
            name=op.f("fk_tasks_agent_call_id_agent_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name=op.f("fk_tasks_goal_id_goals"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tasks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_tasks_goal_id"), ["goal_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_tasks_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_tasks_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_user_id"))
        batch_op.drop_index(batch_op.f("ix_tasks_status"))
        batch_op.drop_index(batch_op.f("ix_tasks_goal_id"))

    op.drop_table("tasks")
    with op.batch_alter_table("agent_calls", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_calls_user_id"))

    op.drop_table("agent_calls")
