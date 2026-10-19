from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Сессия текущего апдейта Telegram. Её открывает DbSessionMiddleware, а хранилище FSM
# пишет через неё же, чтобы смена состояния диалога и изменения в данных
# фиксировались одним коммитом и не спорили за блокировку записи SQLite.
current_session: ContextVar[AsyncSession | None] = ContextVar("current_session", default=None)


def create_engine(db_path: Path | str) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
