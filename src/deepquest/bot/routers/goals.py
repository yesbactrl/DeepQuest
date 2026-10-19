"""Цели и направления: /goals, карточка цели, создание, правка, архив."""

from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackQueryFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.bot import keyboards, texts
from deepquest.bot.filters import TEXT_ANSWER
from deepquest.bot.keyboards import GoalAction, GoalCb
from deepquest.bot.ui import show_in_place
from deepquest.db.models import Goal, User
from deepquest.services import goals


class GoalForm(StatesGroup):
    title = State()  # data: parent_id
    why = State()  # data: parent_id, title
    rename = State()  # data: goal_id
    edit_why = State()  # data: goal_id


async def _send_card(
    bot: Bot, chat_id: int, goal: Goal, *, header: str, just_created: bool = False
) -> None:
    await bot.send_message(
        chat_id,
        f"{header}\n\n{texts.goal_card(goal)}",
        reply_markup=keyboards.goal_card(goal, just_created=just_created),
    )


async def _goal_or_alert(
    callback: CallbackQuery, session: AsyncSession, user: User, goal_id: int
) -> Goal | None:
    goal = await goals.get_active_goal(session, user, goal_id)
    if goal is None:
        await callback.answer(texts.GOAL_NOT_FOUND, show_alert=True)
    return goal


async def _goal_from_state(state: FSMContext, session: AsyncSession, user: User) -> Goal | None:
    goal_id = (await state.get_data()).get("goal_id")
    return await goals.get_active_goal(session, user, goal_id) if goal_id else None


# Список и карточка


async def cmd_goals(message: Message, session: AsyncSession, user: User) -> None:
    items = await goals.list_goals(session, user)
    await message.answer(texts.goals_list(items), reply_markup=keyboards.goals_list(items))


async def show_list(callback: CallbackQuery, bot: Bot, session: AsyncSession, user: User) -> None:
    items = await goals.list_goals(session, user)
    await show_in_place(callback, bot, texts.goals_list(items), keyboards.goals_list(items))


async def open_goal(
    callback: CallbackQuery, callback_data: GoalCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    goal = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if goal is not None:
        await show_in_place(callback, bot, texts.goal_card(goal), keyboards.goal_card(goal))


# Создание цели или направления


async def start_goal_creation(
    bot: Bot, chat_id: int, state: FSMContext, parent: Goal | None
) -> None:
    await state.set_state(GoalForm.title)
    await state.set_data({"parent_id": parent.id if parent else None})
    text = texts.ask_direction_title(parent.title) if parent else texts.ASK_GOAL_TITLE
    await bot.send_message(chat_id, text)


async def new_goal(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await callback.answer()
    await start_goal_creation(bot, callback.from_user.id, state, parent=None)


async def new_direction(
    callback: CallbackQuery,
    callback_data: GoalCb,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    parent = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if parent is None:
        return
    await callback.answer()
    await start_goal_creation(bot, callback.from_user.id, state, parent=parent)


async def title_typed(message: Message, state: FSMContext) -> None:
    try:
        title = goals.clean_title(message.text or "")
    except ValueError:
        await message.answer(texts.GOAL_TITLE_INVALID)
        return
    data = await state.update_data(title=title)
    await state.set_state(GoalForm.why)
    if data.get("parent_id") is None:
        await message.answer(texts.ask_goal_why(title))
    else:
        await message.answer(texts.ask_direction_why(title), reply_markup=keyboards.skip_why())


async def _create(
    bot: Bot, chat_id: int, state: FSMContext, session: AsyncSession, user: User, why: str | None
) -> None:
    data = await state.get_data()
    await state.clear()
    parent = None
    if data.get("parent_id") is not None:
        parent = await goals.get_active_goal(session, user, data["parent_id"])
        if parent is None:
            await bot.send_message(chat_id, texts.GOAL_NOT_FOUND)
            return
    try:
        goal = await goals.create_goal(session, user, data["title"], why, parent)
    except goals.GoalError:
        await bot.send_message(chat_id, texts.GOAL_NOT_FOUND)
        return
    if parent is not None:
        # После направления показываем цель целиком: видно новое направление и можно добавить ещё.
        await _send_card(bot, chat_id, parent, header=texts.DIRECTION_SAVED)
    else:
        await _send_card(bot, chat_id, goal, header=texts.GOAL_SAVED, just_created=True)


async def why_typed(
    message: Message, bot: Bot, state: FSMContext, session: AsyncSession, user: User
) -> None:
    try:
        why = goals.clean_why(message.text or "")
    except ValueError:
        await message.answer(texts.GOAL_WHY_INVALID)
        return
    await _create(bot, message.chat.id, state, session, user, why)


async def why_skipped(
    callback: CallbackQuery, bot: Bot, state: FSMContext, session: AsyncSession, user: User
) -> None:
    if (await state.get_data()).get("parent_id") is None:
        # У цели «зачем» обязательно, кнопку «Пропустить» показываем только для направлений.
        await callback.answer(texts.STALE_BUTTON)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)
    await _create(bot, callback.from_user.id, state, session, user, why=None)


# Правка


async def rename_start(
    callback: CallbackQuery,
    callback_data: GoalCb,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    goal = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if goal is None:
        return
    await callback.answer()
    await state.set_state(GoalForm.rename)
    await state.set_data({"goal_id": goal.id})
    await bot.send_message(callback.from_user.id, texts.ask_rename(goal.title))


async def rename_typed(
    message: Message, bot: Bot, state: FSMContext, session: AsyncSession, user: User
) -> None:
    goal = await _goal_from_state(state, session, user)
    if goal is None:
        await state.clear()
        await message.answer(texts.GOAL_NOT_FOUND)
        return
    try:
        goals.rename_goal(goal, message.text or "")
    except ValueError:
        await message.answer(texts.GOAL_TITLE_INVALID)
        return
    await state.clear()
    await _send_card(bot, message.chat.id, goal, header=texts.GOAL_UPDATED)


async def edit_why_start(
    callback: CallbackQuery,
    callback_data: GoalCb,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    goal = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if goal is None:
        return
    await callback.answer()
    await state.set_state(GoalForm.edit_why)
    await state.set_data({"goal_id": goal.id})
    await bot.send_message(callback.from_user.id, texts.ask_new_why(goal.title))


async def edit_why_typed(
    message: Message, bot: Bot, state: FSMContext, session: AsyncSession, user: User
) -> None:
    goal = await _goal_from_state(state, session, user)
    if goal is None:
        await state.clear()
        await message.answer(texts.GOAL_NOT_FOUND)
        return
    try:
        goals.set_why(goal, message.text or "")
    except ValueError:
        await message.answer(texts.GOAL_WHY_INVALID)
        return
    await state.clear()
    await _send_card(bot, message.chat.id, goal, header=texts.GOAL_UPDATED)


# Архив


async def archive_ask(
    callback: CallbackQuery, callback_data: GoalCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    goal = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if goal is not None:
        await show_in_place(
            callback, bot, texts.confirm_archive(goal), keyboards.confirm_archive(goal)
        )


async def archive_confirmed(
    callback: CallbackQuery, callback_data: GoalCb, bot: Bot, session: AsyncSession, user: User
) -> None:
    goal = await _goal_or_alert(callback, session, user, callback_data.goal_id)
    if goal is None:
        return
    goals.archive_goal(goal, datetime.now(UTC))
    parent = await goals.get_active_goal(session, user, goal.parent_id) if goal.parent_id else None
    if parent is not None:
        await show_in_place(callback, bot, texts.goal_card(parent), keyboards.goal_card(parent))
        return
    items = await goals.list_goals(session, user)
    await show_in_place(callback, bot, texts.goals_list(items), keyboards.goals_list(items))


def create_router() -> Router:
    router = Router(name="goals")
    router.message.filter(F.chat.type == "private")

    def on(action: GoalAction) -> CallbackQueryFilter:
        return GoalCb.filter(F.action == action)

    router.message.register(cmd_goals, Command("goals"))
    router.callback_query.register(show_list, on(GoalAction.LIST))
    router.callback_query.register(open_goal, on(GoalAction.OPEN))
    router.callback_query.register(new_goal, on(GoalAction.NEW))
    router.callback_query.register(new_direction, on(GoalAction.NEW_DIRECTION))
    router.callback_query.register(why_skipped, GoalForm.why, on(GoalAction.SKIP_WHY))
    router.callback_query.register(rename_start, on(GoalAction.RENAME))
    router.callback_query.register(edit_why_start, on(GoalAction.EDIT_WHY))
    router.callback_query.register(archive_ask, on(GoalAction.ARCHIVE))
    router.callback_query.register(archive_confirmed, on(GoalAction.ARCHIVE_YES))

    router.message.register(title_typed, GoalForm.title, TEXT_ANSWER)
    router.message.register(why_typed, GoalForm.why, TEXT_ANSWER)
    router.message.register(rename_typed, GoalForm.rename, TEXT_ANSWER)
    router.message.register(edit_why_typed, GoalForm.edit_why, TEXT_ANSWER)
    return router
