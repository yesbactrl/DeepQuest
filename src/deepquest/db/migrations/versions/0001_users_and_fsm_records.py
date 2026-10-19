"""users and fsm records

Revision ID: 0001
Revises:
Create Date: 2026-10-20 02:34:50.529836

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fsm_records",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_fsm_records")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("tz", sa.String(length=64), nullable=False),
        sa.Column("day_boundary_hour", sa.Integer(), nullable=False),
        sa.Column("daily_norm_min", sa.Integer(), nullable=False),
        sa.Column("morning_at", sa.Time(), nullable=False),
        sa.Column("evening_at", sa.Time(), nullable=False),
        sa.Column("freezes_per_week", sa.Integer(), nullable=False),
        sa.Column("onboarded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("fsm_records")
