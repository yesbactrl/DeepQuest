"""diary scales 1–10

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-22 12:00:00.000000

Настроение, энергия и желание действовать стали 10-балльными, как оценки сфер:
старые оценки 1–5 переводим умножением на 2.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("mood", "energy", "drive")


def upgrade() -> None:
    for column in COLUMNS:
        op.execute(f"UPDATE diary_entries SET {column} = {column} * 2 WHERE {column} IS NOT NULL")


def downgrade() -> None:
    for column in COLUMNS:
        op.execute(
            f"UPDATE diary_entries SET {column} = ({column} + 1) / 2 WHERE {column} IS NOT NULL"
        )
