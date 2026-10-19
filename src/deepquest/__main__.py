"""Точка входа: `uv run deepquest` или `uv run python -m deepquest`."""

import asyncio
import logging
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pydantic import ValidationError

from deepquest.bot.setup import bot_commands, build_dispatcher
from deepquest.config import Settings
from deepquest.db.migrate import upgrade_database
from deepquest.db.session import create_engine, create_sessionmaker

logger = logging.getLogger("deepquest")


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_path)
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(create_sessionmaker(engine), settings.allowed_telegram_ids)
    try:
        await bot.set_my_commands(bot_commands())
        await dispatcher.start_polling(bot)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.exit(
            f"Не удалось прочитать настройки:\n{exc}\n\n"
            "Скопируй .env.example в .env и заполни BOT_TOKEN."
        )

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade_database(settings.database_path)
    logger.info("База: %s", settings.database_path)
    if not settings.allowed_telegram_ids:
        logger.warning("ALLOWED_TELEGRAM_IDS пуст: бот в режиме первой настройки")

    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
