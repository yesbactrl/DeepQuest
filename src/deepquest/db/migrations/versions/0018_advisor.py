"""advisor chats, messages and notes

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-24 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "advisor_chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("session_started", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_advisor_chats_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advisor_chats")),
    )
    with op.batch_alter_table("advisor_chats", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_advisor_chats_user_id"), ["user_id"], unique=False)

    op.create_table(
        "advisor_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["advisor_chats.id"],
            name=op.f("fk_advisor_messages_chat_id_advisor_chats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advisor_messages")),
    )
    with op.batch_alter_table("advisor_messages", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_advisor_messages_chat_id"), ["chat_id"], unique=False)

    op.create_table(
        "advisor_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_advisor_notes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_advisor_notes")),
    )
    with op.batch_alter_table("advisor_notes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_advisor_notes_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    for table in ("advisor_notes", "advisor_messages", "advisor_chats"):
        op.drop_table(table)
