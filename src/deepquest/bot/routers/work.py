"""Работа над задачей: таймер, «Готово», отчёт, вердикт агента, XP и оспаривание."""

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
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
from deepquest.bot.proofs import download_images, extract_report
from deepquest.bot.ui import edit_or_send, show_in_place
from deepquest.db.models import Task, TaskStatus, User
from deepquest.services import tasks, timer, validation
from deepquest.services.days import local_time
from deepquest.services.timer import TimerError
from deepquest.services.validation import ReportError, ValidationOutcome


class ReportForm(StatesGroup):
    waiting = State()  # data: task_id


class DisputeForm(StatesGroup):
    waiting = State()  # data: task_id


def _now() -> datetime:
    return datetime.now(UTC)


def _message_id(callback: CallbackQuery) -> int | None:
    return callback.message.message_id if isinstance(callback.message, Message) else None


async def _task_or_alert(
    callback: CallbackQuery, session: AsyncSession, user: User, task_id: int
) -> Task | None:
    task = await tasks.get_task(session, user, task_id)
    if task is None:
        await callback.answer(texts.TASK_NOT_FOUND, show_alert=True)
    return task


# Таймер. У команд время берём из message.date: если Mac спал, команда обработается
# позже, но засчитается на момент отправки. У кнопок своей даты нет — берём «сейчас».


async def _start(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    session: AsyncSession,
    user: User,
    task: Task,
    at: datetime,
) -> None:
    if not task.is_estimated:
        await edit_or_send(bot, chat_id, None, texts.NOT_ESTIMATED)
        return
    try:
        result = await timer.start(session, user, task, at)
    except TimerError:
        await edit_or_send(bot, chat_id, None, texts.STALE_BUTTON)
        return
    before = await timer.total_minutes(session, task, result.entry.started_at)
    paused_min = await timer.total_minutes(session, result.paused, at) if result.paused else 0
    text = texts.timer_started(
        task, local_time(user, result.entry.started_at), before, result.paused, paused_min
    )
    await edit_or_send(bot, chat_id, message_id, text, keyboards.timer_running(task))


async def _ask_report(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    state: FSMContext,
    session: AsyncSession,
    task: Task,
    at: datetime,
) -> None:
    total = await timer.total_minutes(session, task, at)
    await state.set_state(ReportForm.waiting)
    await state.set_data({"task_id": task.id})
    await edit_or_send(bot, chat_id, message_id, texts.ask_report(task, total))


async def start_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    await callback.answer()
    await _start(bot, callback.from_user.id, _message_id(callback), session, user, task, _now())


async def pause_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    now = _now()
    try:
        await timer.pause(session, user, task, now)
    except TimerError:
        await callback.answer(texts.STALE_BUTTON)
        return
    total = await timer.total_minutes(session, task, now)
    await show_in_place(
        callback, bot, texts.timer_paused(task, total), keyboards.timer_paused(task)
    )


async def done_requested(
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
    now = _now()
    try:
        await timer.finish(session, user, task, now)
    except TimerError:
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    await _ask_report(bot, callback.from_user.id, _message_id(callback), state, session, task, now)


async def cmd_go(message: Message, session: AsyncSession, user: User) -> None:
    entry = await timer.running_entry(session, user)
    task = await tasks.get_task(session, user, entry.task_id) if entry else None
    if entry is not None and task is not None:
        status = texts.running_since(local_time(user, entry.started_at))
        await message.answer(
            texts.task_card(task, status), reply_markup=keyboards.timer_running(task)
        )
        return
    items = await tasks.list_backlog(session, user)
    if not items:
        await message.answer(texts.BACKLOG_EMPTY)
        return
    await message.answer(
        f"{texts.PICK_TASK}\n\n{texts.backlog(items)}", reply_markup=keyboards.backlog(items)
    )


async def cmd_pause(message: Message, session: AsyncSession, user: User) -> None:
    entry = await timer.running_entry(session, user)
    task = await tasks.get_task(session, user, entry.task_id) if entry else None
    if task is None:
        await message.answer(texts.NO_TIMER)
        return
    await timer.pause(session, user, task, message.date)
    total = await timer.total_minutes(session, task, message.date)
    await message.answer(texts.timer_paused(task, total), reply_markup=keyboards.timer_paused(task))


async def cmd_done(
    message: Message, bot: Bot, state: FSMContext, session: AsyncSession, user: User
) -> None:
    entry = await timer.running_entry(session, user)
    task = await tasks.get_task(session, user, entry.task_id) if entry else None
    if task is not None:
        await timer.finish(session, user, task, message.date)
    else:
        # Таймер не идёт, но отчёт по задаче ещё не сдан: просим его снова.
        task = await tasks.last_awaiting_report(session, user)
    if task is None:
        await message.answer(texts.NO_TIMER)
        return
    await _ask_report(bot, message.chat.id, None, state, session, task, message.date)


# Отчёт и вердикт


async def _show_outcome(
    bot: Bot,
    chat_id: int,
    message_id: int | None,
    session: AsyncSession,
    outcome: ValidationOutcome,
    *,
    disputed: bool = False,
) -> None:
    if outcome.agent_failed:
        await edit_or_send(
            bot, chat_id, message_id, texts.REPORT_SAVED_AGENT_DOWN, keyboards.recheck(outcome.task)
        )
        return
    can_dispute = await validation.can_dispute(session, outcome.task)
    await edit_or_send(
        bot,
        chat_id,
        message_id,
        texts.verdict_result(outcome, disputed=disputed),
        keyboards.verdict(outcome.task, can_dispute=can_dispute),
    )


async def report_received(
    message: Message,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    agent: TaskAgent,
) -> None:
    report = extract_report(message)
    if not report.text and not report.files:
        await message.answer(texts.REPORT_NEEDS_CONTENT)
        return
    data = await state.get_data()
    await state.clear()
    task = await tasks.get_task(session, user, data.get("task_id", 0))
    if task is None or task.status != TaskStatus.AWAITING_REPORT:
        await message.answer(texts.TASK_NOT_FOUND)
        return
    placeholder = await message.answer(texts.CHECKING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        images = await download_images(bot, report.files)
        outcome = await validation.submit_report(session, agent, user, task, report, images, _now())
    await _show_outcome(bot, message.chat.id, placeholder.message_id, session, outcome)


async def recheck_requested(
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
    report = await validation.latest_report(session, task)
    if task.status != TaskStatus.AWAITING_REPORT or report is None:
        await callback.answer(texts.STALE_BUTTON)
        return
    await show_in_place(callback, bot, texts.CHECKING)
    async with ChatActionSender.typing(bot=bot, chat_id=callback.from_user.id):
        images = await download_images(bot, report.proofs)
        outcome = await validation.retry(session, agent, user, task, images, _now())
    await _show_outcome(bot, callback.from_user.id, _message_id(callback), session, outcome)


async def why_requested(
    callback: CallbackQuery, callback_data: TaskCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    task = await _task_or_alert(callback, session, user, callback_data.task_id)
    if task is None:
        return
    explanation = await validation.explain(session, task)
    if explanation is None:
        await callback.answer(texts.NO_EXPLANATION, show_alert=True)
        return
    await callback.answer()
    await bot.send_message(callback.from_user.id, texts.why(explanation, task))


async def dispute_requested(
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
    if not await validation.can_dispute(session, task):
        await callback.answer(texts.CANNOT_DISPUTE, show_alert=True)
        return
    await callback.answer()
    await state.set_state(DisputeForm.waiting)
    await state.set_data({"task_id": task.id})
    await bot.send_message(callback.from_user.id, texts.ASK_DISPUTE)


async def dispute_received(
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
    report = await validation.latest_report(session, task) if task else None
    if task is None or report is None:
        await message.answer(texts.TASK_NOT_FOUND)
        return
    placeholder = await message.answer(texts.CHECKING)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        images = await download_images(bot, report.proofs)
        try:
            outcome = await validation.dispute(
                session, agent, user, task, message.text or "", images, _now()
            )
        except ReportError:
            await edit_or_send(bot, message.chat.id, placeholder.message_id, texts.CANNOT_DISPUTE)
            return
    await _show_outcome(
        bot, message.chat.id, placeholder.message_id, session, outcome, disputed=True
    )


def create_router() -> Router:
    router = Router(name="work")
    router.message.filter(F.chat.type == "private")

    def on(action: TaskAction) -> CallbackQueryFilter:
        return TaskCb.filter(F.action == action)

    router.message.register(cmd_go, Command("go"))
    router.message.register(cmd_pause, Command("pause"))
    router.message.register(cmd_done, Command("done"))

    router.callback_query.register(start_requested, on(TaskAction.START))
    router.callback_query.register(pause_requested, on(TaskAction.PAUSE))
    router.callback_query.register(done_requested, on(TaskAction.DONE))
    router.callback_query.register(recheck_requested, on(TaskAction.RECHECK))
    router.callback_query.register(why_requested, on(TaskAction.WHY))
    router.callback_query.register(dispute_requested, on(TaskAction.DISPUTE))

    router.message.register(report_received, ReportForm.waiting, TEXT_ANSWER | F.photo | F.document)
    router.message.register(dispute_received, DisputeForm.waiting, TEXT_ANSWER)
    return router
