from datetime import time

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from deepquest.bot.texts import (
    SETTINGS_REDO_BUTTON,
    format_clock,
    format_minutes,
    format_utc_offset,
)

# Пояса для быстрого выбора. Остальные пользователь пишет текстом.
POPULAR_TIMEZONES = {
    "Europe/Moscow": "Москва",
    "Asia/Yekaterinburg": "Екатеринбург",
    "Asia/Novosibirsk": "Новосибирск",
    "Europe/Kyiv": "Киев",
    "Asia/Almaty": "Алматы",
    "Asia/Bangkok": "Бангкок",
}
NORM_CHOICES_MIN = (30, 60, 90, 120, 180)
MORNING_CHOICES = (time(7), time(8), time(9), time(10))
EVENING_CHOICES = (time(20), time(21), time(22), time(23))


class TimezoneCb(CallbackData, prefix="tz"):
    name: str


class NormCb(CallbackData, prefix="norm"):
    minutes: int


class ClockCb(CallbackData, prefix="clock"):
    # Минуты от полуночи: в callback_data нельзя двоеточие, оно разделитель.
    minutes: int

    @classmethod
    def of(cls, at: time) -> ClockCb:
        return cls(minutes=at.hour * 60 + at.minute)

    def to_time(self) -> time:
        return time(*divmod(self.minutes, 60))


class SettingsCb(CallbackData, prefix="settings"):
    action: str


def timezones(local_tz: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if local_tz:
        city = local_tz.rsplit("/", 1)[-1].replace("_", " ")
        builder.button(
            text=f"Как на этом Mac: {city} ({format_utc_offset(local_tz)})",
            callback_data=TimezoneCb(name=local_tz),
        )
    for name, label in POPULAR_TIMEZONES.items():
        if name != local_tz:
            builder.button(
                text=f"{label} ({format_utc_offset(name)})", callback_data=TimezoneCb(name=name)
            )
    sizes = [1] if local_tz else []
    builder.adjust(*sizes, 2)
    return builder.as_markup()


def daily_norm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for minutes in NORM_CHOICES_MIN:
        builder.button(text=format_minutes(minutes), callback_data=NormCb(minutes=minutes))
    builder.adjust(3, 2)
    return builder.as_markup()


def clock(choices: tuple[time, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for at in choices:
        builder.button(text=format_clock(at), callback_data=ClockCb.of(at))
    builder.adjust(4)
    return builder.as_markup()


def settings() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=SETTINGS_REDO_BUTTON, callback_data=SettingsCb(action="redo"))
    return builder.as_markup()
