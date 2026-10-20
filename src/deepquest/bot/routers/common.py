"""Общие обработчики: /cancel, /stats и всё, что не поймали другие роутеры.
Подключается последним."""

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.bot import texts
from deepquest.db.models import User
from deepquest.services.character import build_character


async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.CANCELLED)


async def cmd_stats(message: Message, session: AsyncSession, user: User) -> None:
    await message.answer(texts.stats(await build_character(session, user, datetime.now(UTC))))


async def any_message(message: Message, state: FSMContext, user: User) -> None:
    # Обычный текст сюда не доходит: его забирает роутер задач или текущий сценарий.
    if await state.get_state() is not None:
        await message.answer(texts.ANSWER_THE_QUESTION)
    elif user.onboarded_at is None:
        await message.answer(texts.NEED_ONBOARDING)
    elif message.text and message.text.startswith("/"):
        await message.answer(texts.UNKNOWN_COMMAND)
    else:
        await message.answer(texts.ONLY_TEXT)


async def stale_callback(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_BUTTON)


def create_router() -> Router:
    router = Router(name="common")
    router.message.filter(F.chat.type == "private")
    router.message.register(cmd_cancel, Command("cancel"))
    router.message.register(cmd_stats, Command("stats"))
    router.message.register(any_message)
    router.callback_query.register(stale_callback)
    return router
