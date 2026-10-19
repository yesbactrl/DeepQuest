from collections.abc import Collection

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.client import TaskAgent
from deepquest.bot import texts
from deepquest.bot.middlewares import DbSessionMiddleware, UserMiddleware, WhitelistMiddleware
from deepquest.bot.routers import common, goals, onboarding, tasks, work
from deepquest.bot.storage import SqlStorage


def build_dispatcher(
    sessionmaker: async_sessionmaker[AsyncSession],
    allowed_telegram_ids: Collection[int],
    agent: TaskAgent,
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=SqlStorage(sessionmaker),
        # Апдейты одного пользователя обрабатываются по очереди: двойной тап
        # по кнопке не прогонит шаг сценария дважды.
        events_isolation=SimpleEventIsolation(),
    )
    # Попадает в обработчики аргументом `agent`.
    dispatcher["agent"] = agent
    dispatcher.update.outer_middleware(WhitelistMiddleware(allowed_telegram_ids))
    dispatcher.update.outer_middleware(DbSessionMiddleware(sessionmaker))
    dispatcher.update.outer_middleware(UserMiddleware())
    # Порядок важен: сценарии с состояниями раньше, «любой текст — новая задача» в tasks,
    # всё остальное — в common.
    dispatcher.include_routers(
        onboarding.create_router(),
        goals.create_router(),
        work.create_router(),
        tasks.create_router(),
        common.create_router(),
    )
    return dispatcher


def bot_commands() -> list[BotCommand]:
    return [BotCommand(command=name, description=text) for name, text in texts.COMMANDS.items()]
