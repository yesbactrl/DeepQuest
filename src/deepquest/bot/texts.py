"""Все тексты бота. Разметка — HTML, поэтому всё, что пришло извне, экранируем."""

from datetime import UTC, datetime, time
from html import escape
from zoneinfo import ZoneInfo

from deepquest.db.models import Goal, User
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN
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
    return (
        f"С возвращением! Текущие настройки:\n\n{settings_summary(user)}\n\n"
        "Цели: /goals · Настройки: /settings"
    )


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
        f"Готово! Вот что получилось:\n\n{settings_summary(user)}\n\nПоменять настройки: /settings"
    )


def settings(user: User) -> str:
    return f"<b>Настройки</b>\n\n{settings_summary(user)}"


SETTINGS_REDO_BUTTON = "Пройти настройку заново"
CANCELLED = "Ок, отменил. Настройки можно пройти заново: /settings"
NOTHING_TO_CANCEL = "Отменять нечего."
NEED_ONBOARDING = "Давай сначала настроимся: /start"
TASKS_SOON = "Скоро сюда можно будет просто написать задачу. Пока доступны /goals и /settings."
ANSWER_THE_QUESTION = "Ответь на вопрос выше или напиши /cancel."
STALE_BUTTON = "Эта кнопка уже не работает."

COMMANDS = {
    "start": "Начать и настроиться",
    "goals": "Цели и направления",
    "settings": "Настройки",
    "cancel": "Отменить текущий шаг",
}


# Цели и направления

GOALS_AFTER_ONBOARDING = (
    "Теперь главное — цели. Заведи 2–4 долгосрочные цели: агент будет привязывать к ним "
    "задачи и оценивать, насколько задача реально двигает цель."
)
GOALS_EMPTY = (
    "<b>Цели</b>\n\nЦелей пока нет. Заведи 2–4 долгосрочные цели: агент будет привязывать "
    "к ним задачи и оценивать, насколько задача реально двигает цель."
)
ASK_GOAL_TITLE = "Как называется цель? Коротко: «Свой доход», «Здоровье», «Английский»."
GOAL_TITLE_INVALID = f"Название — от 1 до {MAX_TITLE_LEN} символов. Попробуй ещё раз."
GOAL_WHY_INVALID = f"Напиши «зачем» текстом, до {MAX_WHY_LEN} символов."
GOAL_NOT_FOUND = "Цель не найдена: возможно, она уже в архиве."
GOAL_SAVED = "✓ Цель сохранена"
DIRECTION_SAVED = "✓ Направление сохранено"
GOAL_UPDATED = "✓ Обновил"
WHY_MISSING = "не указано"

NEW_GOAL_BUTTON = "➕ Новая цель"
ANOTHER_GOAL_BUTTON = "➕ Ещё цель"
NEW_DIRECTION_BUTTON = "➕ Направление"
RENAME_BUTTON = "✏️ Название"
EDIT_WHY_BUTTON = "✏️ Зачем"
ARCHIVE_BUTTON = "🗄 В архив"
ARCHIVE_YES_BUTTON = "Да, в архив"
ARCHIVE_NO_BUTTON = "Отмена"
ALL_GOALS_BUTTON = "← Все цели"
SKIP_BUTTON = "Пропустить"


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def goals_list(goals: list[Goal]) -> str:
    if not goals:
        return GOALS_EMPTY
    blocks = []
    for number, goal in enumerate(goals, start=1):
        lines = [f"{number}. <b>{escape(goal.title)}</b>"]
        if goal.why:
            lines.append(f"<i>{escape(_shorten(goal.why, 120))}</i>")
        lines += [f"   • {escape(child.title)}" for child in goal.active_children]
        blocks.append("\n".join(lines))
    return "<b>Цели</b>\n\n" + "\n\n".join(blocks)


def goal_card(goal: Goal) -> str:
    why = escape(goal.why) if goal.why else f"<i>{WHY_MISSING}</i>"
    if goal.parent is not None:
        return (
            f"🧭 <b>{escape(goal.title)}</b>\n"
            f"Направление цели «{escape(goal.parent.title)}»\n\n"
            f"<b>Зачем:</b> {why}"
        )
    lines = [f"🎯 <b>{escape(goal.title)}</b>", "", f"<b>Зачем:</b> {why}", ""]
    if goal.active_children:
        lines.append("<b>Направления:</b>")
        lines += [f"• {escape(child.title)}" for child in goal.active_children]
    else:
        lines.append(
            "Направлений пока нет. Направление — конкретная линия работы внутри цели, "
            "например «Арбитраж трафика» в цели «Свой доход»."
        )
    return "\n".join(lines)


def ask_goal_why(title: str) -> str:
    return (
        f"Зачем тебе «{escape(title)}»? Пара предложений своими словами: по ним агент поймёт, "
        "какие задачи реально двигают цель."
    )


def ask_direction_title(parent_title: str) -> str:
    return (
        f"Как называется направление внутри «{escape(parent_title)}»? "
        "Например, «Арбитраж трафика» или «Рилсы»."
    )


def ask_direction_why(title: str) -> str:
    return f"Зачем направление «{escape(title)}»? Можно пропустить."


def ask_rename(title: str) -> str:
    return f"Новое название для «{escape(title)}»:"


def ask_new_why(title: str) -> str:
    return f"Новое «зачем» для «{escape(title)}»:"


def confirm_archive(goal: Goal) -> str:
    text = f"Убрать «{escape(goal.title)}» в архив?"
    if goal.active_children:
        text += " Её направления тоже уйдут в архив."
    return text


def back_to_goal_button(goal: Goal) -> str:
    return f"← {_shorten(goal.title, 30)}"
