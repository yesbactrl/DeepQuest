"""Задачи: свободный текст → агент → карточка; уточнение, правка, бэклог."""

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackQueryFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.client import TaskAgent
from deepquest.bot import keyboards, texts
from deepquest.bot.filters import TEXT_ANSWER
from deepquest.bot.keyboards import TaskAction, TaskCb
from deepquest.bot.ui import drop_keyboard, edit_or_send, show_in_place
from deepquest.db.models import Task, TaskStatus, User
from deepquest.services import planning, tasks
from deepquest.services.planning import PlanOutcome


class TaskForm(StatesGroup):
    clarifying = State()  # data: task_id, question_message_id
    correcting = State()  # data: task_id, card_message_id


def _message_id(callback: CallbackQuery) -> int | None:
    return callback.message.message_id if isinstance(callback.message, Message) else None


async def _task_or_alert(
    callback: CallbackQuery, session: AsyncSession, user: User, task_id: int
) -> Task | None:
    task = await tasks.get_task(session, user, task_id)
    if task is None:
        await callback.answer(texts.TASK_NOT_FOUND, show_alert=True)
    return task


async def _show_outcome(
    bot: Bot, chat_id: int, placeholder_id: int, outcome: PlanOutcome, state: FSMContext
) -> None:
    """Первая карточка (или вопрос) встаёт на место «⏳ Оформляю…», остальные идут следом."""
    if outcome.question is not None:
        task = outcome.tasks[0]
        await state.set_state(TaskForm.clarifying)
        await state.set_data({"task_id": task.id, "question_message_id": placeholder_id})
        await edit_or_send(
            bot,
            chat_id,
            placeholder_id,
            texts.clarify_question(outcome.question),
            keyboards.clarifying(task),
        )
        return
    for index, task in enumerate(outcome.tasks):
        card = texts.task_card(task)
        if outcome.agent_failed:
            card = f"{texts.AGENT_FAILED}\n\n{card}"
        message_id = placeholder_id if index == 0 else None
        await edit_or_send(bot, chat_id, message_id, card, keyboards.task_card(task))


# Новая мысль и ответ на уточнение


async def new_task_text(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    if user.onboarded_at is None:
        await message.answer(texts.NEED_ONBOARDING)
        return
    placeholder = await message.answer(texts.PLANNING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        outcome = await planning.plan_from_text(session, agent, user, message.text or "")
    await _show_outcome(bot, message.chat.id, placeholder.message_id, outcome, state)


async def clarification_answered(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    data = await state.get_data()
    await state.clear()
    task = await tasks.get_task(session, user, data.get("task_id", 0))
    if task is None or task.status != TaskStatus.CLARIFYING:
        await message.answer(texts.TASK_NOT_FOUND)
        return
    await drop_keyboard(bot, message.chat.id, data.get("question_message_id"))
    placeholder = await message.answer(texts.PLANNING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        outcome = await planning.answer_clarification(
            session, agent, user, task, message.text or ""
        )
    await _show_outcome(bot, message.chat.id, placeholder.message_id, outcome, state)


async def cancel_clarifying(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    data = await state.get_data()
    await state.clear()
    task = await tasks.get_task(session, user, data.get("task_id", 0))
    if task is not None and task.status == TaskStatus.CLARIFYING:
        tasks.cancel_task(task)
    await message.answer(texts.CANCELLED)


# Правка карточки


async def edit_requested(
    callback: CallbackQuery,
    callback_data: TaskCb,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    if task.status not in {TaskStatus.DRAFT, TaskStatus.OPEN}:
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    await state.set_state(TaskForm.correcting)
    await state.set_data({"task_id": task.id, "card_message_id": _message_id(callback)})
    await bot.send_message(callback.from_user.id, texts.ASK_CORRECTION)


async def correction_typed(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    data = await state.get_data()
    await state.clear()
    task = await tasks.get_task(session, user, data.get("task_id", 0))
    if task is None or task.status not in {TaskStatus.DRAFT, TaskStatus.OPEN}:
        await message.answer(texts.TASK_NOT_FOUND)
        return
    placeholder = await message.answer(texts.REVISING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        revised = await planning.revise(session, agent, user, task, message.text or "")
    if not revised:
        await edit_or_send(bot, message.chat.id, placeholder.message_id, texts.AGENT_FAILED_REVISE)
        return
    task = await tasks.get_task(session, user, task.id)
    assert task is not None
    # Новая карточка — под правкой пользователя, у старой убираем кнопки.
    await edit_or_send(
        bot,
        message.chat.id,
        placeholder.message_id,
        texts.task_card(task),
        keyboards.task_card(task),
    )
    await drop_keyboard(bot, message.chat.id, data.get("card_message_id"))


async def retry_requested(
    callback: CallbackQuery,
    callback_data: TaskCb,
    bot: Bot,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    if task.status != TaskStatus.DRAFT:
        await callback.answer(texts.STALE_BUTTON)
        return
    await show_in_place(callback, bot, texts.PLANNING)
    async with ChatActionSender.typing(bot=bot, chat_id=callback.from_user.id):
        revised = await planning.revise(session, agent, user, task, correction=None)
    task = await tasks.get_task(session, user, task.id)
    assert task is not None
    card = texts.task_card(task)
    if not revised:
        card = f"{texts.AGENT_FAILED}\n\n{card}"
    await edit_or_send(
        bot, callback.from_user.id, _message_id(callback), card, keyboards.task_card(task)
    )


# Решение по карточке


async def save_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    try:
        tasks.save_task(task)
    except tasks.TaskError:
        await callback.answer(texts.STALE_BUTTON)
        return
    await show_in_place(callback, bot, texts.task_card(task, texts.TASK_SAVED))


async def cancel_requested(
    callback: CallbackQuery,
    callback_data: TaskCb,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    was_clarifying = task.status == TaskStatus.CLARIFYING
    try:
        tasks.cancel_task(task)
    except tasks.TaskError:
        await callback.answer(texts.STALE_BUTTON)
        return
    if (await state.get_data()).get("task_id") == task.id:
        await state.clear()
    text = texts.TASK_CANCELLED if was_clarifying else texts.task_card(task, texts.TASK_CANCELLED)
    await show_in_place(callback, bot, text)


# Бэклог


async def cmd_backlog(message: Message, session: AsyncSession, user: User) -> None:
    items = await tasks.list_backlog(session, user)
    await message.answer(texts.backlog(items), reply_markup=keyboards.backlog(items))


async def backlog_requested(
    callback: CallbackQuery, bot: Bot, session: AsyncSession, user: User
) -> None:
    items = await tasks.list_backlog(session, user)
    await show_in_place(callback, bot, texts.backlog(items), keyboards.backlog(items))


async def open_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await tasks.get_task(session, user, callback_data.task_id)
    if task is None or task.status != TaskStatus.OPEN:
        await callback.answer(texts.TASK_NOT_FOUND, show_alert=True)
        return
    await show_in_place(callback, bot, texts.task_card(task), keyboards.task_card(task))


async def remove_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await tasks.get_task(session, user, callback_data.task_id)
    if task is None or task.status != TaskStatus.OPEN:
        await callback.answer(texts.TASK_NOT_FOUND, show_alert=True)
        return
    tasks.cancel_task(task)
    await show_in_place(callback, bot, texts.task_removed(task), keyboards.back_to_backlog())


def create_router() -> Router:
    router = Router(name="tasks")
    router.message.filter(F.chat.type == "private")

    def on(action: TaskAction) -> CallbackQueryFilter:
        return TaskCb.filter(F.action == action)

    router.message.register(cmd_backlog, Command("backlog"))
    router.message.register(cancel_clarifying, Command("cancel"), TaskForm.clarifying)

    router.callback_query.register(save_requested, on(TaskAction.SAVE))
    router.callback_query.register(edit_requested, on(TaskAction.EDIT))
    router.callback_query.register(cancel_requested, on(TaskAction.CANCEL))
    router.callback_query.register(retry_requested, on(TaskAction.RETRY))
    router.callback_query.register(backlog_requested, on(TaskAction.BACKLOG))
    router.callback_query.register(open_requested, on(TaskAction.OPEN))
    router.callback_query.register(remove_requested, on(TaskAction.REMOVE))

    router.message.register(clarification_answered, TaskForm.clarifying, TEXT_ANSWER)
    router.message.register(correction_typed, TaskForm.correcting, TEXT_ANSWER)
    # Любой текст вне сценариев — новая мысль. Сценарии других роутеров ловят свои состояния раньше.
    router.message.register(new_task_text, StateFilter(None), TEXT_ANSWER)
    return router
