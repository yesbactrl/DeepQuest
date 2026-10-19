"""goals

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20 02:44:31.514960

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="goalstatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["goals.id"], name=op.f("fk_goals_parent_id_goals"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_goals_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goals")),
    )
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_goals_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_goals_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_goals_user_id"))
        batch_op.drop_index(batch_op.f("ix_goals_parent_id"))

    op.drop_table("goals")
