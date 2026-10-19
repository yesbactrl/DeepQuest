"""timer reports validations xp

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 03:15:11.521478

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("proofs", sa.JSON(), nullable=False),
        sa.Column("honor_mode", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_reports_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reports_task_id"), ["task_id"], unique=False)

    op.create_table(
        "time_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("stop_reason", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_time_entries_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_time_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_time_entries")),
    )
    with op.batch_alter_table("time_entries", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_time_entries_task_id"), ["task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_time_entries_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            "uq_time_entries_running",
            ["user_id"],
            unique=True,
            sqlite_where=sa.text("ended_at IS NULL"),
        )

    op.create_table(
        "xp_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("task", "correction", name="xpkind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("logical_date", sa.Date(), nullable=False),
        sa.Column("season", sa.String(length=7), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], name=op.f("fk_xp_events_goal_id_goals"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_xp_events_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_xp_events_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_xp_events")),
    )
    with op.batch_alter_table("xp_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_xp_events_season"), ["season"], unique=False)
        batch_op.create_index(batch_op.f("ix_xp_events_task_id"), ["task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_xp_events_user_id"), ["user_id"], unique=False)

    op.create_table(
        "validations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("agent_call_id", sa.Integer(), nullable=True),
        sa.Column(
            "verdict",
            sa.Enum(
                "accepted",
                "partial",
                "rejected",
                name="validationverdict",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("is_dispute", sa.Boolean(), nullable=False),
        sa.Column("dispute_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_call_id"],
            ["agent_calls.id"],
            name=op.f("fk_validations_agent_call_id_agent_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_validations_report_id_reports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_validations_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_validations")),
    )
    with op.batch_alter_table("validations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_validations_task_id"), ["task_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("validations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_validations_task_id"))

    op.drop_table("validations")
    with op.batch_alter_table("xp_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_xp_events_user_id"))
        batch_op.drop_index(batch_op.f("ix_xp_events_task_id"))
        batch_op.drop_index(batch_op.f("ix_xp_events_season"))

    op.drop_table("xp_events")
    with op.batch_alter_table("time_entries", schema=None) as batch_op:
        batch_op.drop_index("uq_time_entries_running", sqlite_where=sa.text("ended_at IS NULL"))
        batch_op.drop_index(batch_op.f("ix_time_entries_user_id"))
        batch_op.drop_index(batch_op.f("ix_time_entries_task_id"))

    op.drop_table("time_entries")
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reports_task_id"))

    op.drop_table("reports")
