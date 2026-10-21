"""Все тексты бота. Разметка — HTML, поэтому всё, что пришло извне, экранируем."""

from datetime import UTC, datetime, time
from html import escape
from zoneinfo import ZoneInfo

from deepquest.db.models import Goal, Task, TaskStatus, User
from deepquest.services.character import WEAK_STAT_MULT, Character, Stat
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN
from deepquest.services.streak import DayMark
from deepquest.services.users import MAX_DAILY_NORM_MIN, MIN_DAILY_NORM_MIN
from deepquest.services.validation import Explanation, ValidationOutcome
from deepquest.services.voice import MAX_VOICE_SECONDS


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
ONLY_TEXT = "Я понимаю текст и голосовые: напиши или надиктуй задачу."
UNKNOWN_COMMAND = "Не знаю такой команды. Есть /backlog, /goals и /settings."
ANSWER_THE_QUESTION = "Ответь на вопрос выше или напиши /cancel."
STALE_BUTTON = "Эта кнопка уже не работает."

COMMANDS = {
    "start": "Начать и настроиться",
    "go": "Запустить таймер",
    "pause": "Поставить таймер на паузу",
    "done": "Закончить задачу и сдать отчёт",
    "backlog": "Бэклог задач",
    "stats": "Уровень, стрик и норма",
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


# Задачи

PLANNING = "⏳ Оформляю задачу…"
REVISING = "⏳ Обновляю карточку…"
AGENT_FAILED = (
    "⚠️ Агент сейчас недоступен, поэтому задача сохранена черновиком без оценки. "
    "Попробуй оценить её ещё раз чуть позже."
)
AGENT_FAILED_REVISE = "⚠️ Не получилось обновить карточку: агент недоступен. Попробуй чуть позже."
ASK_CORRECTION = "Что поправить? Например: «не 2 часа, а 4» или «это к цели Рилсы»."
TASK_SAVED = "✓ В бэклоге"
TASK_CANCELLED = "✗ Отменено"
TASK_REMOVED = "🗑 Убрано из бэклога"
TASK_NOT_FOUND = "Задача не найдена: возможно, её уже убрали."
BACKLOG_EMPTY = (
    "<b>Бэклог</b>\n\nПусто. Напиши или надиктуй голосовым, что хочешь сделать, — я оформлю задачу."
)
NO_GOAL = "не выбрана"
NO_ESTIMATE = "<i>нет, агент был недоступен</i>"


# Голосовые

VOICE_OFF = "Голосовые выключены (VOICE_ENABLED в .env). Напиши текстом."
VOICE_TOO_LONG = (
    f"Голосовое длиннее {MAX_VOICE_SECONDS // 60} минут — слишком долго распознавать. "
    "Раздели на части или напиши текстом."
)
VOICE_EMPTY = "🎙 Ничего не расслышал. Попробуй ещё раз или напиши текстом."


def voice_failed(reason: str | None = None) -> str:
    detail = f" {reason}" if reason else ""
    return f"⚠️ Не получилось распознать голосовое.{detail} Попробуй ещё раз или напиши текстом."


def voice_heard(text: str) -> str:
    return f"🎙 <i>{escape(_shorten(text, 1500))}</i>"


SAVE_BUTTON = "✅ Сохранить"
EDIT_TASK_BUTTON = "✏️ Поправить"
CANCEL_TASK_BUTTON = "✗ Отмена"
RETRY_BUTTON = "🔄 Оценить ещё раз"
REMOVE_TASK_BUTTON = "🗑 Убрать"
BACKLOG_BUTTON = "← Бэклог"
BACKLOG_LIMIT = 30


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_mult(value: float) -> str:
    return f"×{value:g}"


def goal_path(goal: Goal) -> str:
    return f"{goal.parent.title} → {goal.title}" if goal.parent else goal.title


def task_card(task: Task, status_line: str | None = None) -> str:
    lines = [f"📝 <b>{escape(task.title)}</b>", ""]
    if task.expected_result:
        lines.append(f"<b>Результат:</b> {escape(task.expected_result)}")
    goal = escape(goal_path(task.goal)) if task.goal else f"<i>{NO_GOAL}</i>"
    lines.append(f"<b>Цель:</b> {goal}")
    if task.estimate_min is not None and task.value_mult is not None:
        reason = f" — {escape(task.mult_reason)}" if task.mult_reason else ""
        lines.append(f"<b>Оценка:</b> {format_minutes(task.estimate_min)}")
        lines.append(f"<b>Множитель:</b> {format_mult(task.value_mult)}{reason}")
    else:
        lines.append(f"<b>Оценка:</b> {NO_ESTIMATE}")
    if status_line:
        lines += ["", status_line]
    return "\n".join(lines)


def clarify_question(question: str) -> str:
    return f"❓ {escape(question)}"


def task_removed(task: Task) -> str:
    return f"{TASK_REMOVED}: {escape(task.title)}"


def backlog(tasks: list[Task]) -> str:
    if not tasks:
        return BACKLOG_EMPTY
    total = sum(task.estimate_min or 0 for task in tasks)
    count = f"{len(tasks)} {plural(len(tasks), 'задача', 'задачи', 'задач')}"
    lines = [f"<b>Бэклог</b> · {count} · ~{format_minutes(total)}", ""]
    for number, task in enumerate(tasks[:BACKLOG_LIMIT], start=1):
        meta = []
        if task.estimate_min is not None:
            meta.append(format_minutes(task.estimate_min))
        if task.value_mult is not None:
            meta.append(format_mult(task.value_mult))
        if task.goal:
            meta.append(escape(goal_path(task.goal)))
        running = "⏱ " if task.status == TaskStatus.RUNNING else ""
        lines.append(f"{number}. {running}{escape(task.title)}")
        if meta:
            lines.append(f"    <i>{' · '.join(meta)}</i>")
    if len(tasks) > BACKLOG_LIMIT:
        lines += ["", f"…и ещё {len(tasks) - BACKLOG_LIMIT}"]
    return "\n".join(lines)


# Таймер, отчёт и XP

START_BUTTON = "▶️ Старт"
RESUME_BUTTON = "▶️ Продолжить"
PAUSE_BUTTON = "⏸ Пауза"
DONE_BUTTON = "✅ Готово"
WHY_BUTTON = "❓ Почему столько?"
SELF_ACCEPT_BUTTON = "✅ Засчитать без проверки"
DISPUTE_BUTTON = "⚖️ Оспорить"
RECHECK_BUTTON = "🔄 Проверить ещё раз"

NO_TIMER = "Таймер не запущен. Открой задачу в /backlog и нажми «Старт»."
PICK_TASK = "Выбери задачу и нажми «Старт»."
NOT_ESTIMATED = "Сначала нужна оценка: нажми «Оценить ещё раз» на карточке задачи."
CHECKING = "⏳ Проверяю отчёт…"
REPORT_NEEDS_CONTENT = "Пришли отчёт текстом или голосовым, скрином или ссылкой."
REPORT_SAVED_AGENT_DOWN = (
    "⚠️ Отчёт сохранён, но агент сейчас недоступен. Нажми «Проверить ещё раз» чуть позже."
)
ASK_DISPUTE = "С чем не согласен? Напиши, что я упустил: что именно сделано, факты, ссылки."
CANNOT_DISPUTE = "Эту проверку уже нельзя оспорить: оспорить можно один раз."
NO_EXPLANATION = "По этой задаче ещё нет начисления."

VERDICT_HEADERS = {
    "accepted": "✅ Засчитано",
    "partial": "🟡 Засчитано частично",
    "rejected": "❌ Не засчитано",
}
VERDICT_LABELS = {"accepted": "засчитано", "partial": "частично", "rejected": "не засчитано"}


def running_since(started_local: datetime) -> str:
    return f"⏱ Таймер идёт с {started_local:%H:%M}"


def timer_started(
    task: Task,
    started_local: datetime,
    before_min: int,
    paused: Task | None = None,
    paused_min: int = 0,
) -> str:
    lines = []
    if paused is not None:
        lines += [f"⏸ «{escape(paused.title)}» на паузе, по ней {format_minutes(paused_min)}.", ""]
    since = f"Таймер идёт с {started_local:%H:%M}."
    if before_min:
        since += f" До этого по задаче: {format_minutes(before_min)}."
    lines += [
        f"⏱ <b>{escape(task.title)}</b>",
        since,
        "",
        "Закончишь — жми «Готово», и я попрошу короткий отчёт.",
    ]
    return "\n".join(lines)


def timer_paused(task: Task, total_min: int) -> str:
    return f"⏸ Пауза: <b>{escape(task.title)}</b>\nВсего по задаче: {format_minutes(total_min)}."


def ask_report(task: Task, total_min: int) -> str:
    if total_min == 0 and task.estimate_min is not None:
        # Таймер не обязателен: без него время засчитывается по оценке.
        lines = [
            f"✅ <b>{escape(task.title)}</b>: засчитаю по оценке — "
            f"{format_minutes(task.estimate_min)}. Ушло иначе — поправишь время в вебе.",
            "",
        ]
    else:
        lines = [f"✅ <b>{escape(task.title)}</b>: {format_minutes(total_min)} по таймеру.", ""]
    lines.append(
        "Что получилось? Напиши коротко: что сделал и что понял. Приложи пруф — скрин или "
        "ссылку. Без пруфа засчитаю «на честном слове» с ×0.8. Не хочешь отчёт — "
        "«Засчитать без проверки»."
    )
    return "\n".join(lines)


def _signed_xp(amount: int) -> str:
    return f"+{amount} XP" if amount > 0 else f"{amount} XP"


def stat_and_skill(task: Task) -> tuple[str | None, str | None]:
    """Стат (цель) и скилл (направление) задачи. Цель и её родитель должны быть подгружены."""
    goal = task.goal
    if goal is None:
        return None, None
    return (goal.parent.title, goal.title) if goal.parent else (goal.title, None)


def xp_split(amount: int, stat: str | None, skill: str | None) -> str:
    """«+60 XP общий · +60 Здоровье · +60 Спорт»: XP идёт сразу в уровень, стат и скилл."""
    signed = _signed_xp(amount)
    if amount == 0 or stat is None:
        return signed
    number = signed.removesuffix(" XP")
    parts = [f"{signed} общий", f"{number} {escape(stat)}"]
    if skill is not None:
        parts.append(f"{number} {escape(skill)}")
    return " · ".join(parts)


def verdict_result(outcome: ValidationOutcome, *, disputed: bool = False) -> str:
    assert outcome.validation is not None
    header = VERDICT_HEADERS[outcome.validation.verdict.value]
    if outcome.validation.self_check:
        header = "✅ Засчитано без проверки"
    if disputed:
        header = f"⚖️ Пересмотрел. {header}"
    stat, skill = stat_and_skill(outcome.task)
    lines = [f"{header} · {xp_split(outcome.xp_delta, stat, skill)}"]
    weak = outcome.breakdown.weak_mult if outcome.breakdown else 1.0
    if weak > 1 and outcome.xp_delta > 0 and not disputed and stat is not None:
        lines.append(f"💪 «{escape(stat)}» — самый слабый стат: {format_mult(weak)} к XP")
    if outcome.validation.comment:
        lines += ["", escape(outcome.validation.comment)]
    lines += ["", f"Всего: {outcome.total_xp} XP"]
    return "\n".join(lines)


def why(explanation: Explanation, task: Task) -> str:
    b = explanation.breakdown
    time_line = f"• Время: {format_minutes(b.counted_min)}"
    if b.capped:
        time_line += (
            f" (по таймеру {format_minutes(b.actual_min)}, "
            "но засчитываю не больше двух оценок задачи)"
        )
    value_reason = f" — {escape(task.mult_reason)}" if task.mult_reason else ""
    proof = "на честном слове" if b.honor_mode else "есть"
    lines = [
        f"<b>Почему {b.amount} XP</b>",
        "",
        time_line,
        f"• Ценность задачи: {format_mult(b.value_mult)}{value_reason}",
        f"• Проверка отчёта: {VERDICT_LABELS[b.verdict]} {format_mult(b.validation_mult)} — "
        f"{escape(explanation.validation.reason)}",
        f"• Пруф: {proof} {format_mult(b.proof_mult)}",
    ]
    formula = f"{b.counted_min} мин × {b.value_mult:g} × {b.validation_mult:g} × {b.proof_mult:g}"
    if b.weak_mult != 1:
        lines.append(f"• Самый слабый стат: {format_mult(b.weak_mult)} — бонус отстающей цели")
        formula += f" × {b.weak_mult:g}"
    lines += ["", f"{formula} = {b.amount} XP"]
    return "\n".join(lines)


# Статистика

MONTH_NAMES = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]  # fmt: skip
DAY_MARKS = {"met": "🟩", "frozen": "🟦", "missed": "🟥"}


def _day_mark(mark: DayMark) -> str:
    if mark.status == "today":
        return "✅" if mark.focus_min >= mark.norm_min else "⏳"
    return DAY_MARKS[mark.status]


def _stat_line(stat: Stat) -> str:
    line = f"• {escape(stat.goal.title)} — ур. <b>{stat.level.level}</b>"
    if stat.skills:
        skills = " · ".join(f"{escape(s.goal.title)} {s.level.level}" for s in stat.skills)
        line += f" ({skills})"
    if stat.weakest:
        line += f"\n   ⚠️ самый слабый стат: {format_mult(WEAK_STAT_MULT)} к XP"
    return line


def stats(character: Character) -> str:
    summary = character.summary
    total, season, streak = summary.total, summary.season_level, summary.streak
    month = MONTH_NAMES[int(summary.season[5:7]) - 1]
    today = (
        "норма выполнена ✓"
        if streak.today_met
        else f"до нормы {format_minutes(streak.norm_min - streak.today_focus_min)}"
    )
    days = plural(streak.current, "день", "дня", "дней")
    return "\n".join(
        [
            "📊 <b>Статистика</b>",
            "",
            f"Уровень <b>{total.level}</b> · {total.xp} XP "
            f"(до {total.level + 1}-го — {total.next_xp - total.xp} XP)",
            f"Сезон «{month}»: уровень <b>{season.level}</b> · {season.xp} XP",
            f"Сегодня: {format_minutes(streak.today_focus_min)} из "
            f"{format_minutes(streak.norm_min)} — {today}",
            f"Стрик: <b>{streak.current}</b> {days} · лучший {streak.best} · "
            f"заморозок осталось {streak.freezes_left} из {streak.freezes_per_week}",
            "",
            "".join(_day_mark(mark) for mark in streak.recent),
            "🟩 норма · 🟦 заморозка · 🟥 пропуск",
            *(["", "<b>Статы</b>", *map(_stat_line, character.stats)] if character.stats else []),
        ]
    )
