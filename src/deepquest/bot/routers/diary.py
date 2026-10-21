"""Дневник в боте: `/d как ты` — сразу запись, просто `/d` — бот спросит и запишет ответ."""

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.base import TaskAgent
from deepquest.bot import texts
from deepquest.bot.filters import TEXT_ANSWER
from deepquest.bot.ui import edit_or_send
from deepquest.db.models import User
from deepquest.services import diary


class DiaryForm(StatesGroup):
    waiting = State()


async def _save(
    message: Message, bot: Bot, session: AsyncSession, user: User, agent: TaskAgent, text: str
) -> None:
    placeholder = await message.answer(texts.DIARY_SAVING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        outcome = await diary.add_entry(session, agent, user, text, message.date)
    await edit_or_send(
        bot,
        message.chat.id,
        placeholder.message_id,
        texts.diary_entry(outcome.entry, agent_failed=outcome.agent_failed),
    )


async def cmd_diary(
    message: Message,
    command: CommandObject,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    text = (command.args or "").strip()
    if not text:
        await state.set_state(DiaryForm.waiting)
        await message.answer(texts.ASK_DIARY)
        return
    await _save(message, bot, session, user, agent, text)


async def diary_answered(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    await state.clear()
    await _save(message, bot, session, user, agent, message.text or "")


async def cancel_diary(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.DIARY_CANCELLED)


def create_router() -> Router:
    router = Router(name="diary")
    router.message.register(cmd_diary, Command("d"))
    router.message.register(cancel_diary, Command("cancel"), DiaryForm.waiting)
    router.message.register(diary_answered, DiaryForm.waiting, TEXT_ANSWER)
    return router
