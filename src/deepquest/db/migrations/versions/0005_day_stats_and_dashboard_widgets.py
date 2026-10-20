"""day stats and dashboard widgets

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20 17:46:22.875052

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_dashboard_widgets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_widgets")),
    )
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_dashboard_widgets_user_id"), ["user_id"], unique=False)

    op.create_table(
        "day_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("logical_date", sa.Date(), nullable=False),
        sa.Column("focus_min", sa.Integer(), nullable=False),
        sa.Column("norm_min", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("met", "missed", "frozen", name="daystatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_day_stats_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_stats")),
        sa.UniqueConstraint("user_id", "logical_date", name=op.f("uq_day_stats_user_id")),
    )
    with op.batch_alter_table("day_stats", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_day_stats_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dashboard_seeded", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("dashboard_seeded")

    with op.batch_alter_table("day_stats", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_day_stats_user_id"))

    op.drop_table("day_stats")
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_dashboard_widgets_user_id"))

    op.drop_table("dashboard_widgets")
