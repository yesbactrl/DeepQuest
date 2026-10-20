"""Голосовые сообщения. Распознаём до роутеров, дальше сообщение идёт как обычный текст:
любой сценарий, который ждёт текст (новая задача, уточнение, правка, отчёт), понимает и голос.
"""

import logging
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, TelegramObject
from aiogram.utils.chat_action import ChatActionSender

from deepquest.bot import texts
from deepquest.bot.middlewares import Handler
from deepquest.services.voice import MAX_VOICE_SECONDS, Transcriber, VoiceError

logger = logging.getLogger(__name__)


class VoiceMiddleware(BaseMiddleware):
    def __init__(self, transcriber: Transcriber | None) -> None:
        self._transcriber = transcriber

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if not isinstance(event, Message) or event.voice is None:
            return await handler(event, data)
        text = await self._recognize(event, data["bot"])
        if text is None:
            return None
        return await handler(event.model_copy(update={"text": text}), data)

    async def _recognize(self, message: Message, bot: Bot) -> str | None:
        assert message.voice is not None
        if self._transcriber is None:
            await message.answer(texts.VOICE_OFF)
            return None
        if message.voice.duration > MAX_VOICE_SECONDS:
            await message.answer(texts.VOICE_TOO_LONG)
            return None
        try:
            async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
                buffer = await bot.download(message.voice.file_id)
                text = await self._transcriber.transcribe(buffer.read() if buffer else b"")
        except VoiceError as exc:
            await message.answer(texts.voice_failed(str(exc)))
            return None
        except Exception:
            logger.exception("Не удалось распознать голосовое")
            await message.answer(texts.voice_failed())
            return None
        if not text:
            await message.answer(texts.VOICE_EMPTY)
            return None
        # Показываем, что расслышали: если ошибся, видно сразу, а не по странной карточке.
        await message.answer(texts.voice_heard(text))
        return text
