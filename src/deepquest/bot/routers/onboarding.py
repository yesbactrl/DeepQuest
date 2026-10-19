"""Онбординг (/start) и настройки (/settings): пояс, норма, время утра и вечера."""

from datetime import UTC, datetime, time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from deepquest.bot import keyboards, texts
from deepquest.bot.keyboards import ClockCb, NormCb, SettingsCb, TimezoneCb
from deepquest.bot.parsing import (
    local_timezone_name,
    parse_clock_time,
    parse_duration_minutes,
    resolve_timezone,
)
from deepquest.db.models import User
from deepquest.services import users

# Свободный текст, но не команда: /cancel и прочие должны доходить до своих обработчиков.
TEXT_ANSWER = F.text & ~F.text.startswith("/")


class Onboarding(StatesGroup):
    timezone = State()
    daily_norm = State()
    morning = State()
    evening = State()


async def _close_keyboard(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


async def _send(
    bot: Bot, chat_id: int, *parts: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    await bot.send_message(chat_id, "\n\n".join(parts), reply_markup=reply_markup)


async def start_onboarding(bot: Bot, chat_id: int, state: FSMContext) -> None:
    await state.set_state(Onboarding.timezone)
    await _send(
        bot, chat_id, texts.ASK_TIMEZONE, reply_markup=keyboards.timezones(local_timezone_name())
    )


async def cmd_start(message: Message, bot: Bot, state: FSMContext, user: User) -> None:
    if user.onboarded_at is not None:
        await state.clear()
        await message.answer(texts.welcome_back(user))
        return
    await message.answer(texts.WELCOME)
    await start_onboarding(bot, message.chat.id, state)


async def cmd_settings(message: Message, user: User) -> None:
    await message.answer(texts.settings(user), reply_markup=keyboards.settings())


async def settings_redo(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await _close_keyboard(callback)
    await start_onboarding(bot, callback.from_user.id, state)


# Шаг 1: часовой пояс


async def _apply_timezone(bot: Bot, chat_id: int, state: FSMContext, user: User, tz: str) -> None:
    users.set_timezone(user, tz)
    await state.set_state(Onboarding.daily_norm)
    await _send(
        bot,
        chat_id,
        texts.step_done("Пояс", texts.format_timezone(tz)),
        texts.ASK_DAILY_NORM,
        reply_markup=keyboards.daily_norm(),
    )


async def timezone_picked(
    callback: CallbackQuery, callback_data: TimezoneCb, bot: Bot, state: FSMContext, user: User
) -> None:
    await _close_keyboard(callback)
    await _apply_timezone(bot, callback.from_user.id, state, user, callback_data.name)


async def timezone_typed(message: Message, bot: Bot, state: FSMContext, user: User) -> None:
    tz = resolve_timezone(message.text or "")
    if tz is None:
        await message.answer(texts.TIMEZONE_NOT_UNDERSTOOD)
        return
    await _apply_timezone(bot, message.chat.id, state, user, tz)


# Шаг 2: дневная норма


async def _apply_daily_norm(
    bot: Bot, chat_id: int, state: FSMContext, user: User, minutes: int | None
) -> None:
    try:
        if minutes is None:
            raise ValueError("Duration not understood")
        users.set_daily_norm(user, minutes)
    except ValueError:
        await _send(bot, chat_id, texts.DAILY_NORM_NOT_UNDERSTOOD)
        return
    await state.set_state(Onboarding.morning)
    await _send(
        bot,
        chat_id,
        texts.step_done("Норма", texts.format_minutes(user.daily_norm_min)),
        texts.ASK_MORNING,
        reply_markup=keyboards.clock(keyboards.MORNING_CHOICES),
    )


async def daily_norm_picked(
    callback: CallbackQuery, callback_data: NormCb, bot: Bot, state: FSMContext, user: User
) -> None:
    await _close_keyboard(callback)
    await _apply_daily_norm(bot, callback.from_user.id, state, user, callback_data.minutes)


async def daily_norm_typed(message: Message, bot: Bot, state: FSMContext, user: User) -> None:
    minutes = parse_duration_minutes(message.text or "")
    await _apply_daily_norm(bot, message.chat.id, state, user, minutes)


# Шаг 3: утреннее сообщение


async def _apply_morning(
    bot: Bot, chat_id: int, state: FSMContext, user: User, at: time | None
) -> None:
    if at is None:
        await _send(bot, chat_id, texts.CLOCK_NOT_UNDERSTOOD)
        return
    users.set_morning_at(user, at)
    await state.set_state(Onboarding.evening)
    await _send(
        bot,
        chat_id,
        texts.step_done("Утро", texts.format_clock(at)),
        texts.ASK_EVENING,
        reply_markup=keyboards.clock(keyboards.EVENING_CHOICES),
    )


async def morning_picked(
    callback: CallbackQuery, callback_data: ClockCb, bot: Bot, state: FSMContext, user: User
) -> None:
    await _close_keyboard(callback)
    await _apply_morning(bot, callback.from_user.id, state, user, callback_data.to_time())


async def morning_typed(message: Message, bot: Bot, state: FSMContext, user: User) -> None:
    await _apply_morning(bot, message.chat.id, state, user, parse_clock_time(message.text or ""))


# Шаг 4: вечерняя сводка и финал


async def _apply_evening(
    bot: Bot, chat_id: int, state: FSMContext, user: User, at: time | None
) -> None:
    if at is None:
        await _send(bot, chat_id, texts.CLOCK_NOT_UNDERSTOOD)
        return
    try:
        users.set_evening_at(user, at)
    except ValueError:
        await _send(
            bot,
            chat_id,
            texts.evening_before_morning(user.morning_at),
            reply_markup=keyboards.clock(keyboards.EVENING_CHOICES),
        )
        return
    users.finish_onboarding(user, datetime.now(UTC))
    await state.clear()
    await _send(
        bot,
        chat_id,
        texts.step_done("Вечер", texts.format_clock(at)),
        texts.onboarding_finished(user),
    )


async def evening_picked(
    callback: CallbackQuery, callback_data: ClockCb, bot: Bot, state: FSMContext, user: User
) -> None:
    await _close_keyboard(callback)
    await _apply_evening(bot, callback.from_user.id, state, user, callback_data.to_time())


async def evening_typed(message: Message, bot: Bot, state: FSMContext, user: User) -> None:
    await _apply_evening(bot, message.chat.id, state, user, parse_clock_time(message.text or ""))


def create_router() -> Router:
    router = Router(name="onboarding")
    router.message.filter(F.chat.type == "private")

    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_settings, Command("settings"))
    router.callback_query.register(settings_redo, SettingsCb.filter(F.action == "redo"))

    router.callback_query.register(timezone_picked, Onboarding.timezone, TimezoneCb.filter())
    router.message.register(timezone_typed, Onboarding.timezone, TEXT_ANSWER)
    router.callback_query.register(daily_norm_picked, Onboarding.daily_norm, NormCb.filter())
    router.message.register(daily_norm_typed, Onboarding.daily_norm, TEXT_ANSWER)
    router.callback_query.register(morning_picked, Onboarding.morning, ClockCb.filter())
    router.message.register(morning_typed, Onboarding.morning, TEXT_ANSWER)
    router.callback_query.register(evening_picked, Onboarding.evening, ClockCb.filter())
    router.message.register(evening_typed, Onboarding.evening, TEXT_ANSWER)
    return router
