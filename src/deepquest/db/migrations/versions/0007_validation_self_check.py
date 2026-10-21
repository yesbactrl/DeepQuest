"""validation self_check

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("validations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("self_check", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("validations", schema=None) as batch_op:
        batch_op.drop_column("self_check")
