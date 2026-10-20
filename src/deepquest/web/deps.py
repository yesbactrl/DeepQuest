from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.base import TaskAgent
from deepquest.db.models import User
from deepquest.services.proofs import ProofStore, TelegramDownload
from deepquest.services.users import get_or_create_user
from deepquest.services.voice import Transcriber


@dataclass(frozen=True)
class WebContext:
    sessionmaker: async_sessionmaker[AsyncSession]
    # Пользователь у веба один — владелец бота (первый из ALLOWED_TELEGRAM_IDS).
    owner_telegram_id: int | None
    agent: TaskAgent
    proofs: ProofStore
    # Бот в том же процессе: через него веб читает скриншоты, присланные в Telegram.
    telegram_download: TelegramDownload | None = None
    # None — голосовой ввод выключен.
    transcriber: Transcriber | None = None


def get_context(request: Request) -> WebContext:
    return request.app.state.context


async def get_session(
    context: Annotated[WebContext, Depends(get_context)],
) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос; коммит, если обработчик завершился без ошибки."""
    async with context.sessionmaker() as session:
        yield session
        await session.commit()


async def get_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    context: Annotated[WebContext, Depends(get_context)],
) -> User:
    if context.owner_telegram_id is None:
        raise HTTPException(
            503, "Сначала настрой бота: впиши свой telegram_id в ALLOWED_TELEGRAM_IDS"
        )
    return await get_or_create_user(session, context.owner_telegram_id)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
UserDep = Annotated[User, Depends(get_user)]
ContextDep = Annotated[WebContext, Depends(get_context)]
