from collections.abc import Collection

from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseEventIsolation
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.bot.middlewares import DbSessionMiddleware, UserMiddleware, WhitelistMiddleware
from deepquest.bot.routers import common, goals, onboarding
from deepquest.bot.storage import SqlStorage


def build_dispatcher(
    sessionmaker: async_sessionmaker[AsyncSession],
    allowed_telegram_ids: Collection[int],
    events_isolation: BaseEventIsolation | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=SqlStorage(sessionmaker),
        # Апдейты одного пользователя обрабатываются по очереди: двойной тап
        # по кнопке не прогонит шаг сценария дважды.
        events_isolation=events_isolation or SimpleEventIsolation(),
    )
    dispatcher.update.outer_middleware(WhitelistMiddleware(allowed_telegram_ids))
    dispatcher.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dispatcher.update.outer_middleware(UserMiddleware())
    dispatcher.include_routers(
        onboarding.create_router(), goals.create_router(), common.create_router()
    )
    return dispatcher


def bot_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=text) for name, text in texts.COMMANDS.items()]
