import sqlite3
from datetime import date, timedelta
from pathlib import Path

from deepquest.services.backup import backup_database, backup_path


def _make_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("create table notes (text)")
        db.execute("insert into notes values ('привет')")


def test_backup_once_per_day_with_data(tmp_path: Path) -> None:
    db = tmp_path / "deepquest.db"
    _make_db(db)
    backups = tmp_path / "backups"
    day = date(2026, 10, 24)

    made = backup_database(db, backups, day)

    assert made == backup_path(backups, day)
    with sqlite3.connect(made) as copy:
        assert copy.execute("select text from notes").fetchall() == [("привет",)]
    # Второй раз за тот же день копия не делается.
    assert backup_database(db, backups, day) is None
    assert not list(backups.glob("*.part"))


def test_backup_keeps_only_last_copies(tmp_path: Path) -> None:
    db = tmp_path / "deepquest.db"
    _make_db(db)
    backups = tmp_path / "backups"
    start = date(2026, 10, 1)

    for offset in range(5):
        backup_database(db, backups, start + timedelta(days=offset), keep=3)

    kept = sorted(path.name for path in backups.iterdir())
    assert kept == [
        "deepquest-2026-10-03.db",
        "deepquest-2026-10-04.db",
        "deepquest-2026-10-05.db",
    ]
