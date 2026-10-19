from datetime import time
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from deepquest.bot import texts
from deepquest.bot.texts import (
    SETTINGS_REDO_BUTTON,
    format_clock,
    format_minutes,
    format_utc_offset,
)
from deepquest.db.models import Goal, Task, TaskStatus

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


class GoalAction(StrEnum):
    LIST = "list"
    OPEN = "open"
    NEW = "new"
    NEW_DIRECTION = "sub"
    RENAME = "rename"
    EDIT_WHY = "why"
    SKIP_WHY = "skip"
    ARCHIVE = "archive"
    ARCHIVE_YES = "archive_yes"


class GoalCb(CallbackData, prefix="goal"):
    action: GoalAction
    goal_id: int = 0


def goals_list(goals: list[Goal]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for number, goal in enumerate(goals, start=1):
        builder.button(
            text=f"{number}. {goal.title}",
            callback_data=GoalCb(action=GoalAction.OPEN, goal_id=goal.id),
        )
    builder.button(text=texts.NEW_GOAL_BUTTON, callback_data=GoalCb(action=GoalAction.NEW))
    builder.adjust(1)
    return builder.as_markup()


def goal_card(goal: Goal, *, just_created: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    sizes = [2]
    builder.button(
        text=texts.RENAME_BUTTON, callback_data=GoalCb(action=GoalAction.RENAME, goal_id=goal.id)
    )
    builder.button(
        text=texts.EDIT_WHY_BUTTON,
        callback_data=GoalCb(action=GoalAction.EDIT_WHY, goal_id=goal.id),
    )
    if goal.parent is None:
        for child in goal.active_children:
            builder.button(
                text=f"🧭 {child.title}",
                callback_data=GoalCb(action=GoalAction.OPEN, goal_id=child.id),
            )
            sizes.append(1)
        builder.button(
            text=texts.NEW_DIRECTION_BUTTON,
            callback_data=GoalCb(action=GoalAction.NEW_DIRECTION, goal_id=goal.id),
        )
        sizes.append(1)
        if just_created:
            builder.button(
                text=texts.ANOTHER_GOAL_BUTTON, callback_data=GoalCb(action=GoalAction.NEW)
            )
            sizes.append(1)
    builder.button(
        text=texts.ARCHIVE_BUTTON, callback_data=GoalCb(action=GoalAction.ARCHIVE, goal_id=goal.id)
    )
    if goal.parent is not None:
        builder.button(
            text=texts.back_to_goal_button(goal.parent),
            callback_data=GoalCb(action=GoalAction.OPEN, goal_id=goal.parent.id),
        )
    else:
        builder.button(text=texts.ALL_GOALS_BUTTON, callback_data=GoalCb(action=GoalAction.LIST))
    sizes.append(2)
    builder.adjust(*sizes)
    return builder.as_markup()


def confirm_archive(goal: Goal) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=texts.ARCHIVE_YES_BUTTON,
        callback_data=GoalCb(action=GoalAction.ARCHIVE_YES, goal_id=goal.id),
    )
    builder.button(
        text=texts.ARCHIVE_NO_BUTTON, callback_data=GoalCb(action=GoalAction.OPEN, goal_id=goal.id)
    )
    builder.adjust(2)
    return builder.as_markup()


def skip_why() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.SKIP_BUTTON, callback_data=GoalCb(action=GoalAction.SKIP_WHY))
    return builder.as_markup()


class TaskAction(StrEnum):
    SAVE = "save"
    EDIT = "edit"
    CANCEL = "cancel"
    RETRY = "retry"
    OPEN = "open"
    REMOVE = "remove"
    BACKLOG = "backlog"
    START = "start"
    PAUSE = "pause"
    DONE = "done"
    WHY = "why"
    RECHECK = "recheck"
    DISPUTE = "dispute"


class TaskCb(CallbackData, prefix="task"):
    action: TaskAction
    task_id: int = 0


def _task_button(builder: InlineKeyboardBuilder, text: str, action: TaskAction, task: Task) -> None:
    builder.button(text=text, callback_data=TaskCb(action=action, task_id=task.id))


def task_card(task: Task) -> InlineKeyboardMarkup | None:
    """Кнопки карточки зависят от статуса: черновик решаем, задачу из бэклога правим."""
    builder = InlineKeyboardBuilder()
    if task.status == TaskStatus.DRAFT:
        sizes = []
        if not task.is_estimated:
            _task_button(builder, texts.RETRY_BUTTON, TaskAction.RETRY, task)
            sizes.append(1)
        _task_button(builder, texts.SAVE_BUTTON, TaskAction.SAVE, task)
        _task_button(builder, texts.EDIT_TASK_BUTTON, TaskAction.EDIT, task)
        _task_button(builder, texts.CANCEL_TASK_BUTTON, TaskAction.CANCEL, task)
        builder.adjust(*sizes, 3)
        return builder.as_markup()
    if task.status == TaskStatus.OPEN:
        sizes = []
        if task.is_estimated:
            _task_button(builder, texts.START_BUTTON, TaskAction.START, task)
            _task_button(builder, texts.DONE_BUTTON, TaskAction.DONE, task)
            sizes.append(2)
        _task_button(builder, texts.EDIT_TASK_BUTTON, TaskAction.EDIT, task)
        _task_button(builder, texts.REMOVE_TASK_BUTTON, TaskAction.REMOVE, task)
        builder.button(text=texts.BACKLOG_BUTTON, callback_data=TaskCb(action=TaskAction.BACKLOG))
        builder.adjust(*sizes, 2, 1)
        return builder.as_markup()
    if task.status == TaskStatus.RUNNING:
        return timer_running(task, with_backlog=True)
    return None


def saved(task: Task) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.START_BUTTON, TaskAction.START, task)
    return builder.as_markup()


def timer_running(task: Task, *, with_backlog: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.PAUSE_BUTTON, TaskAction.PAUSE, task)
    _task_button(builder, texts.DONE_BUTTON, TaskAction.DONE, task)
    if with_backlog:
        builder.button(text=texts.BACKLOG_BUTTON, callback_data=TaskCb(action=TaskAction.BACKLOG))
    builder.adjust(2, 1)
    return builder.as_markup()


def timer_paused(task: Task) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.RESUME_BUTTON, TaskAction.START, task)
    _task_button(builder, texts.DONE_BUTTON, TaskAction.DONE, task)
    builder.button(text=texts.BACKLOG_BUTTON, callback_data=TaskCb(action=TaskAction.BACKLOG))
    builder.adjust(2, 1)
    return builder.as_markup()


def verdict(task: Task, *, can_dispute: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.WHY_BUTTON, TaskAction.WHY, task)
    if can_dispute:
        _task_button(builder, texts.DISPUTE_BUTTON, TaskAction.DISPUTE, task)
    builder.adjust(2)
    return builder.as_markup()


def recheck(task: Task) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.RECHECK_BUTTON, TaskAction.RECHECK, task)
    return builder.as_markup()


def clarifying(task: Task) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _task_button(builder, texts.CANCEL_TASK_BUTTON, TaskAction.CANCEL, task)
    return builder.as_markup()


def backlog(tasks: list[Task]) -> InlineKeyboardMarkup | None:
    if not tasks:
        return None
    builder = InlineKeyboardBuilder()
    for number, task in enumerate(tasks[: texts.BACKLOG_LIMIT], start=1):
        _task_button(builder, str(number), TaskAction.OPEN, task)
    builder.adjust(5)
    return builder.as_markup()


def back_to_backlog() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=texts.BACKLOG_BUTTON, callback_data=TaskCb(action=TaskAction.BACKLOG))
    return builder.as_markup()
