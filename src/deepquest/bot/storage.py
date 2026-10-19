from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StateType, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.db.models import FsmRecord
from deepquest.db.session import current_session


class SqlStorage(BaseStorage):
    """FSM-хранилище aiogram в SQLite: сценарии переживают перезапуск бота.

    Внутри обработчика пишет через сессию текущего апдейта (`current_session`),
    поэтому смена состояния коммитится вместе с данными или откатывается вместе с ними.
    Вне обработчика (например, aiogram читает состояние до наших middleware)
    открывает свою короткую сессию.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._key_builder = DefaultKeyBuilder(with_destiny=True)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        session = current_session.get()
        if session is not None:
            yield session
            return
        async with self._sessionmaker() as own_session:
            yield own_session
            await own_session.commit()

    async def _get(self, session: AsyncSession, key: StorageKey) -> FsmRecord | None:
        return await session.get(FsmRecord, self._key_builder.build(key))

    async def _get_or_add(self, session: AsyncSession, key: StorageKey) -> FsmRecord:
        record = await self._get(session, key)
        if record is None:
            record = FsmRecord(key=self._key_builder.build(key), state=None, data={})
            session.add(record)
        return record

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with self._session() as session:
            (await self._get_or_add(session, key)).state = value

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._session() as session:
            record = await self._get(session, key)
            return record.state if record else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        async with self._session() as session:
            (await self._get_or_add(session, key)).data = dict(data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._session() as session:
            record = await self._get(session, key)
            return dict(record.data) if record else {}

    async def close(self) -> None:
        pass
