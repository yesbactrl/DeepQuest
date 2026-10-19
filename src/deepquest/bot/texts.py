"""Все тексты бота. Разметка — HTML, поэтому всё, что пришло извне, экранируем."""

from datetime import UTC, datetime, time
from html import escape
from zoneinfo import ZoneInfo

from deepquest.db.models import User
from deepquest.services.users import MAX_DAILY_NORM_MIN, MIN_DAILY_NORM_MIN


def format_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} ч {rest} мин"
    if hours:
        return f"{hours} ч"
    return f"{rest} мин"


def format_clock(at: time) -> str:
    return at.strftime("%H:%M")


def format_utc_offset(tz: str) -> str:
    offset = datetime.now(UTC).astimezone(ZoneInfo(tz)).utcoffset()
    total_minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if total_minutes >= 0 else "−"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")


def format_timezone(tz: str) -> str:
    if tz == "UTC" or tz.startswith("Etc/"):
        return format_utc_offset(tz)
    return f"{tz} ({format_utc_offset(tz)})"


def settings_summary(user: User) -> str:
    return (
        f"Пояс: <b>{escape(format_timezone(user.tz))}</b>\n"
        f"Дневная норма: <b>{format_minutes(user.daily_norm_min)}</b>\n"
        f"Утреннее сообщение: <b>{format_clock(user.morning_at)}</b>\n"
        f"Вечерняя сводка: <b>{format_clock(user.evening_at)}</b>\n"
        f"День заканчивается в <b>{user.day_boundary_hour:02d}:00</b>\n"
        f"Заморозок стрика в неделю: <b>{user.freezes_per_week}</b>"
    )


def setup_mode(telegram_id: int) -> str:
    return (
        "DeepQuest ещё не настроен.\n\n"
        f"Твой telegram_id: <code>{telegram_id}</code>\n"
        f"Впиши его в .env (<code>ALLOWED_TELEGRAM_IDS={telegram_id}</code>) "
        "и перезапусти бота."
    )


WELCOME = (
    "Привет! Это <b>DeepQuest</b> — система личной прокачки: цели, задачи, таймер "
    "и XP за реальные шаги.\n\n"
    "Сначала пара настроек, это займёт минуту."
)


def welcome_back(user: User) -> str:
    return f"С возвращением! Текущие настройки:\n\n{settings_summary(user)}\n\nИзменить: /settings"


ASK_TIMEZONE = (
    "В каком ты часовом поясе? Выбери кнопку или напиши город («Берлин», «Bangkok») "
    "или смещение от UTC («+7»)."
)
TIMEZONE_NOT_UNDERSTOOD = (
    "Не узнал такой пояс. Напиши город, например «Москва» или «Bangkok», "
    "или смещение от UTC, например «+7»."
)
ASK_DAILY_NORM = (
    "Сколько времени в день ты хочешь вкладывать в себя? Это дневная норма для стрика.\n"
    "Выбери кнопку или напиши, например, «90 мин» или «1.5 ч»."
)
DAILY_NORM_NOT_UNDERSTOOD = (
    "Не понял. Напиши время, например «45 мин» или «2 ч». "
    f"Норма — от {format_minutes(MIN_DAILY_NORM_MIN)} до {format_minutes(MAX_DAILY_NORM_MIN)}."
)
ASK_MORNING = "Во сколько присылать утреннее сообщение с планом на день?"
ASK_EVENING = "А во сколько вечернюю сводку?"
CLOCK_NOT_UNDERSTOOD = "Не понял время. Напиши, например, «8:30» или «21»."


def evening_before_morning(morning: time) -> str:
    return (
        f"Вечерняя сводка должна быть позже утреннего сообщения ({format_clock(morning)}). "
        "Выбери другое время."
    )


def step_done(label: str, value: str) -> str:
    return f"✓ {label}: <b>{escape(value)}</b>"


def onboarding_finished(user: User) -> str:
    return (
        f"Готово! Вот что получилось:\n\n{settings_summary(user)}\n\n"
        "Скоро здесь появятся цели и задачи. Поменять настройки: /settings"
    )


def settings(user: User) -> str:
    return f"<b>Настройки</b>\n\n{settings_summary(user)}"


SETTINGS_REDO_BUTTON = "Пройти настройку заново"
CANCELLED = "Ок, отменил. Настройки можно пройти заново: /settings"
NOTHING_TO_CANCEL = "Отменять нечего."
NEED_ONBOARDING = "Давай сначала настроимся: /start"
TASKS_SOON = "Скоро сюда можно будет просто написать задачу. Пока доступны /settings."
ANSWER_THE_QUESTION = "Ответь на вопрос выше или напиши /cancel."
STALE_BUTTON = "Эта кнопка уже не работает."

COMMANDS = {
    "start": "Начать и настроиться",
    "settings": "Настройки",
    "cancel": "Отменить текущий шаг",
}
