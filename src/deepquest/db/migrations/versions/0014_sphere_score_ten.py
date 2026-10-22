"""sphere scores 1–10

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-22 10:00:00.000000

Оценки сфер в дневнике стали 10-балльными: старые оценки 1–5 переводим умножением на 2.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE diary_spheres SET score = score * 2 WHERE score IS NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE diary_spheres SET score = (score + 1) / 2 WHERE score IS NOT NULL")
