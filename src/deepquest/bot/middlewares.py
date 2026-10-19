import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, Update
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.db.session import current_session
from deepquest.services.users import get_or_create_user

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class WhitelistMiddleware(BaseMiddleware):
    """Пропускает апдейты только от разрешённых telegram_id.

    Пустой список — режим первой настройки: в ответ на сообщение в личке бот
    присылает отправителю его telegram_id и больше ничего не делает.
    """

    def __init__(self, allowed_ids: Collection[int]) -> None:
        self._allowed = frozenset(allowed_ids)

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: TelegramUser | None = data.get("event_from_user")
        if user is None:
            return None
        if user.id in self._allowed:
            return await handler(event, data)

        chat: Chat | None = data.get("event_chat")
        if not self._allowed:
            logger.warning("Setup mode: update from telegram_id=%s", user.id)
            is_private_message = (
                isinstance(event, Update)
                and event.message is not None
                and chat is not None
                and chat.type == "private"
            )
            if is_private_message:
                await data["bot"].send_message(chat.id, texts.setup_mode(user.id))
        else:
            logger.warning("Rejected update from telegram_id=%s", user.id)
        return None


class DbSessionMiddleware(BaseMiddleware):
    """Одна сессия БД на апдейт; коммит, если обработчик завершился без ошибки."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self._sessionmaker() as session:
            token = current_session.set(session)
            try:
                data["session"] = session
                result = await handler(event, data)
                await session.commit()
                return result
            finally:
                current_session.reset(token)


class UserMiddleware(BaseMiddleware):
    """Кладёт в обработчик запись пользователя из БД (создаёт при первом обращении)."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        telegram_user: TelegramUser = data["event_from_user"]
        data["user"] = await get_or_create_user(data["session"], telegram_user.id)
        return await handler(event, data)
