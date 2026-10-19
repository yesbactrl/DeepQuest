"""Общие приёмы показа: перерисовать сообщение на месте или прислать новое."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)


def _not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in exc.message


async def edit_or_send(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Правит сообщение `message_id`; если его нет или править нельзя — шлёт новое."""
    if message_id is not None:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
            )
            return
        except TelegramBadRequest as exc:
            if _not_modified(exc):
                return
            logger.info("Cannot edit message %s, sending a new one: %s", message_id, exc.message)
    await bot.send_message(chat_id, text, reply_markup=reply_markup)


async def show_in_place(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Перерисовывает сообщение с нажатой кнопкой."""
    await callback.answer()
    message_id = callback.message.message_id if isinstance(callback.message, Message) else None
    await edit_or_send(bot, callback.from_user.id, message_id, text, reply_markup)


async def drop_keyboard(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Убирает кнопки со старого сообщения, чтобы нельзя было нажать устаревшее."""
    if message_id is None:
        return
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest as exc:
        if not _not_modified(exc):
            logger.info("Cannot drop keyboard of %s: %s", message_id, exc.message)
