from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(db_path: Path) -> Config:
    config = Config()
    # Config использует интерполяцию configparser, поэтому «%» в пути нужно экранировать.
    config.set_main_option("script_location", str(MIGRATIONS_DIR).replace("%", "%%"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}".replace("%", "%%"))
    return config


def upgrade_database(db_path: Path) -> None:
    """Применяет все миграции. Вызывается синхронно до запуска event loop."""
    command.upgrade(alembic_config(db_path), "head")
