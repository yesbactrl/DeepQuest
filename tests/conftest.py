from collections.abc import AsyncGenerator, AsyncIterator, Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import EditMessageText, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, Update
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from deepquest.bot.setup import build_dispatcher
from deepquest.db.migrate import upgrade_database
from deepquest.db.session import create_engine, create_sessionmaker


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    upgrade_database(path)
    return path


@pytest.fixture
async def engine(db_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(db_path)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


class FakeTelegramSession(BaseSession):
    """Вместо сети записывает запросы бота к Telegram и отвечает правдоподобно."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
        raise NotImplementedError
        yield b""

    async def close(self) -> None:
        pass


class BotHarness:
    """Диспетчер DeepQuest с фейковым Telegram: шлём апдейты, смотрим ответы."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], allowed_ids: Collection[int]
    ) -> None:
        self.telegram = FakeTelegramSession()
        self.bot = Bot(
            "42:TEST",
            session=self.telegram,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dispatcher = build_dispatcher(sessionmaker, allowed_ids)
        self._update_id = 0

    def _next_update_id(self) -> int:
        self._update_id += 1
        return self._update_id

    @staticmethod
    def _user(user_id: int) -> TelegramUser:
        return TelegramUser(id=user_id, is_bot=False, first_name="Test")

    async def send(self, user_id: int, text: str) -> None:
        message = Message(
            message_id=self._update_id + 1000,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
            text=text,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._next_update_id(), message=message)
        )

    async def press(self, user_id: int, callback_data: str) -> None:
        question = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            text="question",
        )
        callback = CallbackQuery(
            id=str(self._update_id),
            from_user=self._user(user_id),
            chat_instance="test",
            data=callback_data,
            message=question,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._next_update_id(), callback_query=callback)
        )

    @property
    def sent(self) -> list[SendMessage]:
        return [r for r in self.telegram.requests if isinstance(r, SendMessage)]

    @property
    def screens(self) -> list[SendMessage | EditMessageText]:
        """Всё, что пользователь видит: новые сообщения и перерисованные."""
        return [r for r in self.telegram.requests if isinstance(r, SendMessage | EditMessageText)]

    @property
    def last_text(self) -> str:
        return self.screens[-1].text

    def button(self, label: str) -> str:
        """callback_data кнопки с этим текстом на последнем экране с клавиатурой."""
        for screen in reversed(self.screens):
            if isinstance(screen.reply_markup, InlineKeyboardMarkup):
                for row in screen.reply_markup.inline_keyboard:
                    for button in row:
                        if label in button.text and button.callback_data:
                            return button.callback_data
                raise AssertionError(f"No button {label!r} on the last keyboard")
        raise AssertionError("No keyboard was shown")

    async def tap(self, user_id: int, label: str) -> None:
        await self.press(user_id, self.button(label))
