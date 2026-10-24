"""Ежедневный бэкап базы. Копировать файл живой SQLite-базы небезопасно, поэтому копия
делается встроенным `backup` — он даёт целостный снимок, даже пока бот и веб пишут.

Наличие копии проверяется раз в час, а сама копия делается раз в календарный день: так сон
Mac не мешает — после пробуждения копия за новый день появится с первой же проверкой.
Хранятся последние KEEP копий, папка лежит рядом с базой и попадает в Time Machine.
"""

import asyncio
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

KEEP = 14
CHECK_EVERY_S = 60 * 60
PREFIX = "deepquest-"


def backup_path(backups_dir: Path, day: date) -> Path:
    return backups_dir / f"{PREFIX}{day.isoformat()}.db"


def backup_database(db_path: Path, backups_dir: Path, day: date, keep: int = KEEP) -> Path | None:
    """Снимок базы за `day`, если его ещё нет. Возвращает путь новой копии или None."""
    target = backup_path(backups_dir, day)
    if target.exists():
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".db.part")
    with sqlite3.connect(db_path) as source, sqlite3.connect(partial) as copy:
        source.backup(copy)
    partial.replace(target)
    for old in sorted(backups_dir.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink()
    return target


async def run_backups(db_path: Path, backups_dir: Path) -> None:
    """Фоновая задача процесса: раз в час проверяет, есть ли копия за сегодня."""
    while True:
        try:
            made = await asyncio.to_thread(
                backup_database, db_path, backups_dir, datetime.now().date()
            )
            if made is not None:
                logger.info("Бэкап базы: %s", made)
        except Exception:
            logger.exception("Бэкап базы не удался")
        await asyncio.sleep(CHECK_EVERY_S)
