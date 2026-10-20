"""Точка входа: `uv run deepquest` или `uv run python -m deepquest`.

В одном процессе работают бот (long polling) и веб (uvicorn), с одной базой и одними
сервисами. Ctrl+C (или SIGTERM от launchd) останавливает оба аккуратно.
"""

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Iterator

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pydantic import ValidationError

from deepquest.agent.setup import build_agent
from deepquest.bot.proofs import telegram_download
from deepquest.bot.setup import bot_commands, build_dispatcher
from deepquest.config import Settings
from deepquest.db.migrate import upgrade_database
from deepquest.db.session import create_engine, create_sessionmaker
from deepquest.services.proofs import ProofStore
from deepquest.services.voice import WhisperTranscriber
from deepquest.web.app import create_app

logger = logging.getLogger("deepquest")


class _WebServer(uvicorn.Server):
    # Сигналы ловит main(): иначе uvicorn и aiogram перехватывают Ctrl+C каждый по-своему.
    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def _serve_web(server: _WebServer) -> None:
    try:
        await server.serve()
    except SystemExit:
        # uvicorn выходит через sys.exit, если не смог занять порт. Бот при этом пусть работает.
        logger.error("Веб не запустился: порт %s занят?", server.config.port)


async def _poll_bot(dispatcher: Dispatcher, bot: Bot) -> None:
    await bot.set_my_commands(bot_commands())
    await dispatcher.start_polling(bot, handle_signals=False)


async def run(settings: Settings) -> None:
    engine = create_engine(settings.database_path)
    sessionmaker = create_sessionmaker(engine)
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    agent = build_agent(settings)
    logger.info("Агент: %s", agent.description)
    # Одно хранилище пруфов на бота и веб: отчёт из одного можно перепроверить из другого.
    proofs = ProofStore(settings.data_dir / "proofs")
    transcriber = None
    warm_up = None
    if settings.voice_enabled:
        transcriber = WhisperTranscriber(
            settings.voice_model, settings.voice_language or None, settings.models_dir
        )
        logger.info("Голос: %s", transcriber.description)
        warm_up = asyncio.create_task(transcriber.warm_up(), name="voice-warm-up")
    dispatcher = build_dispatcher(
        sessionmaker, settings.allowed_telegram_ids, agent.agent, proofs, transcriber
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    workers = [asyncio.create_task(_poll_bot(dispatcher, bot), name="bot")]
    server = None
    if settings.web_enabled:
        owner = settings.allowed_telegram_ids[0] if settings.allowed_telegram_ids else None
        app = create_app(
            sessionmaker,
            owner,
            settings.web_dist_dir,
            agent.agent,
            proofs,
            telegram_download(bot),
            transcriber,
        )
        server = _WebServer(
            uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_level="info")
        )
        workers.append(asyncio.create_task(_serve_web(server), name="web"))
        logger.info("Веб: http://%s:%s", settings.web_host, settings.web_port)

    try:
        # Останавливаемся по сигналу или если бот упал.
        stopper = asyncio.create_task(stop.wait())
        await asyncio.wait([stopper, workers[0]], return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
    finally:
        logger.info("Останавливаюсь…")
        if warm_up is not None:
            warm_up.cancel()
        if server is not None:
            server.should_exit = True
        with contextlib.suppress(RuntimeError):  # поллинг уже остановлен
            await dispatcher.stop_polling()
        results = await asyncio.gather(*workers, return_exceptions=True)
        for task, result in zip(workers, results, strict=True):
            if isinstance(result, Exception):
                logger.error("%s завершился с ошибкой", task.get_name(), exc_info=result)
        await bot.session.close()
        await agent.aclose()
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
    if settings.web_host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning("Веб слушает %s, а входа в нём нет: открыт всем в сети", settings.web_host)

    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
