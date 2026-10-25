"""MCP-сервер DeepQuest: `uv run deepquest mcp`.

Советник — любой MCP-клиент (Claude Desktop, Claude Code, позже чат в вебе) — читает через
него задачи, цели, план, дневник, сон и итоги и может сделать несколько безопасных действий:
завести задачу, поставить её на день, записать в дневник или сон. Удалять, закрывать задачи
и начислять XP он не может.

Отдельный процесс рядом со службой: база в режиме WAL, читать и писать из двух процессов
можно. Ответы — компактный текст, а не JSON: так модель тратит меньше контекста.
"""

import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.base import TaskAgent
from deepquest.agent.schemas import VALUE_MULTIPLIERS, TaskDraft
from deepquest.db.models import DiaryEntry, SleepKind, Task, TaskStatus, User
from deepquest.services import advisor as memory
from deepquest.services import (
    diary,
    goals,
    plan,
    review,
    search,
    sleep,
    stats,
    streak,
    tasks,
    timer,
    validation,
    xp,
)
from deepquest.services.days import user_logical_date
from deepquest.services.goals import goal_path
from deepquest.services.levels import level_of
from deepquest.services.review import PeriodKind
from deepquest.services.sleep import SleepInput
from deepquest.services.users import get_or_create_user

logger = logging.getLogger(__name__)

SOURCE_MARK = "[советник]"
MAX_TEXT = 1500

INSTRUCTIONS = """DeepQuest — система личной прокачки пользователя: цели (это сферы жизни и статы
персонажа) с направлениями, задачи за XP (XP ≈ минуты × множитель ценности 0.5–2), дневной
план, дневник состояния (настроение, энергия, желание действовать — по 1–10, факторы, заметки
по сферам), сон (ночной и дневной, относится к дню пробуждения) и итоги недели или месяца.

Ты — советник пользователя. Начинай с `overview`, остальное подтягивай инструментами по мере
надобности, не грузи всё сразу. Опирайся на данные, называй задачи и цифры. Перед действием,
которое что-то меняет (create_task, schedule_task, add_diary_entry, log_sleep), коротко скажи,
что сделаешь, если пользователь сам об этом прямо не попросил. Устойчивое о пользователе
(предпочтения, договорённости) сохраняй через remember; память видна в overview.
Пиши по-русски, на «ты»."""

STATUS = {
    TaskStatus.CLARIFYING: "вопрос агента",
    TaskStatus.DRAFT: "черновик",
    TaskStatus.OPEN: "в бэклоге",
    TaskStatus.RUNNING: "идёт таймер",
    TaskStatus.AWAITING_REPORT: "ждёт отчёта",
    TaskStatus.DONE: "готово",
    TaskStatus.REJECTED: "не засчитано",
    TaskStatus.CANCELLED: "отменена",
}
FILTERS: dict[str, list[TaskStatus]] = {
    "backlog": [TaskStatus.OPEN],
    "work": [TaskStatus.RUNNING, TaskStatus.AWAITING_REPORT],
    "done": [TaskStatus.DONE, TaskStatus.REJECTED],
    "drafts": [TaskStatus.DRAFT, TaskStatus.CLARIFYING],
    "all": [s for s in TaskStatus if s != TaskStatus.CANCELLED],
}
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


class AdvisorError(ValueError):
    """Ошибка, понятная модели: уходит ей текстом, а не трейсбеком."""


def _h(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} ч {m:02d} мин" if h else f"{m} мин"


def _clock(minutes: int | None) -> str:
    return "—" if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"


def _day(day: date) -> str:
    return f"{day:%d.%m} ({WEEKDAYS[day.weekday()]})"


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _task_line(task: Task, xp: int | None = None, minutes: int | None = None) -> str:
    parts = [f"#{task.id} «{task.title}» — {STATUS[task.status]}"]
    if task.goal is not None:
        parts.append(goal_path(task.goal))
    if task.estimate_min is not None and task.value_mult is not None:
        parts.append(f"оценка {_h(task.estimate_min)}, ×{task.value_mult:g}")
    if task.planned_for is not None:
        parts.append(f"на {_day(task.planned_for)}")
    if minutes:
        parts.append(f"потрачено {_h(minutes)}")
    if xp:
        parts.append(f"{xp:+d} XP")
    return "; ".join(parts)


def _entry_scores(entry: DiaryEntry) -> str:
    scores = [
        f"{name} {value}"
        for name, value in (
            ("настроение", entry.mood),
            ("энергия", entry.energy),
            ("желание", entry.drive),
        )
        if value is not None
    ]
    return ", ".join(scores)


class Advisor:
    """Инструменты советника. Каждый вызов — своя сессия базы и свой коммит."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        owner_telegram_id: int,
        agent: TaskAgent | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._owner = owner_telegram_id
        self._agent = agent
        self._clock = clock

    async def _run(self, work: Callable[[AsyncSession, User, datetime], Awaitable[str]]) -> str:
        async with self._sessionmaker() as session:
            user = await get_or_create_user(session, self._owner)
            result = await work(session, user, self._clock())
            await session.commit()
            return result

    # Чтение

    async def overview(self) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            today = user_logical_date(user, now)
            local = sleep.to_local(user, now)
            info = await streak.streak_info(session, user, now)
            total = level_of(await xp.total_xp(session, user))
            lines = [
                f"Сейчас {local:%d.%m.%Y %H:%M} ({WEEKDAYS[local.weekday()]}), пояс {user.tz}. "
                f"Логический день {today} (граница дня в {user.day_boundary_hour}:00).",
                f"Уровень {total.level}, всего {total.xp} XP.",
            ]
            if info.paused:
                lines.append("Норма и стрик на паузе.")
            else:
                lines.append(
                    f"Норма {_h(info.norm_min)} в день, сегодня фокуса {_h(info.today_focus_min)}; "
                    f"стрик {info.current} дн."
                )
            for running in await timer.running_entries(session, user):
                task = await tasks.get_task(session, user, running.task_id)
                if task is not None:
                    lines.append(f"Идёт таймер: #{task.id} «{task.title}».")

            day_plan = await plan.build_plan(session, user, now, days=1)
            todays = day_plan.days[0].tasks
            lines.append("")
            lines.append(f"План на сегодня ({_h(day_plan.days[0].load_min)} по оценкам):")
            lines += [f"- {_task_line(t)}" for t in todays] or ["- пусто"]
            if day_plan.overdue:
                lines.append(f"Просрочено с прошлых дней: {len(day_plan.overdue)} задач.")
            lines.append(f"В бэклоге без дня: {len(day_plan.unplanned)} задач.")

            last = await session.scalar(
                select(DiaryEntry)
                .where(
                    DiaryEntry.user_id == user.id,
                    DiaryEntry.logical_date >= today - timedelta(days=1),
                )
                .order_by(DiaryEntry.created_at.desc())
                .limit(1)
            )
            if last is not None:
                lines.append("")
                lines.append(
                    f"Последняя запись в дневнике ({_day(last.logical_date)}, "
                    f"{diary.PARTS_OF_DAY[last.part_of_day]}): "
                    f"{last.summary or _clip(last.text, 200)}"
                    + (f" [{_entry_scores(last)}]" if _entry_scores(last) else "")
                )
            nights = sleep.by_day(
                user, await sleep.sessions_between(session, user, local.date(), local.date())
            )
            if local.date() in nights:
                d = nights[local.date()]
                lines.append(
                    f"Сон сегодня: {_h(d.total_min)} (норма {_h(user.sleep_goal_min)})"
                    + (
                        f", лёг {d.bedtime:%H:%M}, встал {d.wake:%H:%M}"
                        if d.bedtime and d.wake
                        else ""
                    )
                )
            else:
                lines.append("Сон за сегодня не записан.")

            lines.append("")
            lines.append("Цели (id — для фильтров и новых задач):")
            for goal in await goals.list_goals(session, user):
                lines.append(f"- {goal.id}: {goal.title}")
                lines += [f"  - {d.id}: {d.title}" for d in goal.active_children]
            notes = await memory.list_notes(session, user)
            if notes:
                lines.append("")
                lines.append("Что ты помнишь о пользователе (remember / forget):")
                lines += [f"- #{note.id}: {note.text}" for note in notes]
            return "\n".join(lines)

        return await self._run(work)

    async def list_goals(self) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            items = await goals.list_goals(session, user)
            if not items:
                return "Целей пока нет."
            by_id = await stats.goal_stats(session, user, items, now)
            lines = []
            for goal in items:
                s = by_id[goal.id]
                lines.append(
                    f"{goal.id}: «{goal.title}» — зачем: {goal.why or 'не указано'}. "
                    f"Всего {s.xp} XP, {_h(s.minutes)}, задач закрыто {s.done_tasks}, "
                    f"без движения {s.idle_days} дн."
                    + (" Только рост." if goal.growth_only else "")
                )
                for d in goal.active_children:
                    ds = by_id[d.id]
                    lines.append(
                        f"  {d.id}: «{d.title}» — {ds.xp} XP, {_h(ds.minutes)}, "
                        f"без движения {ds.idle_days} дн."
                    )
            return "\n".join(lines)

        return await self._run(work)

    async def list_tasks(
        self, status: str = "backlog", goal_id: int | None = None, limit: int = 50
    ) -> str:
        if status not in FILTERS:
            raise AdvisorError(f"status — одно из: {', '.join(FILTERS)}")

        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            goal_ids = None
            if goal_id is not None:
                goal = await goals.get_active_goal(session, user, goal_id)
                goal_ids = {goal_id, *(d.id for d in goal.children)} if goal else {goal_id}
            items = await tasks.list_tasks(session, user, FILTERS[status], goal_ids)
            items = items[: max(1, min(limit, 200))]
            if not items:
                return "Задач нет."
            totals = await stats.task_totals(session, items, now)
            return "\n".join(_task_line(t, totals[t.id].xp, totals[t.id].minutes) for t in items)

        return await self._run(work)

    async def get_task(self, task_id: int) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            task = await tasks.get_task(session, user, task_id)
            if task is None:
                raise AdvisorError(f"Задачи #{task_id} нет.")
            totals = (await stats.task_totals(session, [task], now))[task.id]
            lines = [_task_line(task, totals.xp, totals.minutes)]
            if task.expected_result:
                lines.append(f"Результат: {task.expected_result}")
            if task.mult_reason:
                lines.append(f"Почему такой множитель: {task.mult_reason}")
            lines.append(f"Исходная мысль: {_clip(task.source_text, 600)}")
            lines.append(f"Создана {sleep.to_local(user, task.created_at):%d.%m.%Y %H:%M}.")
            report = await validation.latest_report(session, task)
            if report is not None:
                lines.append(f"Отчёт: {_clip(report.text, 800)}")
            verdict = await validation.latest_validation(session, task)
            if verdict is not None:
                lines.append(f"Вердикт: {verdict.verdict} — {verdict.reason}. {verdict.comment}")
            return "\n".join(lines)

        return await self._run(work)

    async def get_plan(self, days: int = 7) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            result = await plan.build_plan(session, user, now, days=max(1, min(days, 14)))
            norm = "" if user.streak_paused_at else f" (норма {_h(user.daily_norm_min)})"
            lines = [f"План{norm}:"]
            for day in result.days:
                lines.append(f"{_day(day.day)}: {_h(day.load_min)}, {day.load_xp} XP")
                lines += [f"  - {_task_line(t)}" for t in day.tasks]
            if result.overdue:
                lines.append("Просрочено:")
                lines += [f"  - {_task_line(t)}" for t in result.overdue]
            lines.append(f"Без дня (бэклог): {len(result.unplanned)} — см. list_tasks.")
            if result.energy_today is not None or result.drive_today is not None:
                lines.append(
                    f"Сегодня по дневнику: энергия {result.energy_today or '—'}, "
                    f"желание {result.drive_today or '—'}."
                )
            return "\n".join(lines)

        return await self._run(work)

    async def get_diary(self, days: int = 7, goal_id: int | None = None) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            items = await diary.list_days(session, user, now, max(1, min(days, 120)), goal_id)
            if not items:
                return "Записей за этот период нет."
            titles = {g.id: g.title for g in await goals.list_goals(session, user)}
            lines = []
            for day in items:
                lines.append(
                    f"## {_day(day.day)}: фокус {_h(day.focus_min)}, {day.xp} XP; среднее — "
                    f"настроение {day.mood or '—'}, энергия {day.energy or '—'}, "
                    f"желание {day.drive or '—'}"
                )
                for e in reversed(day.entries):
                    lines.append(
                        f"- #{e.id} {sleep.to_local(user, e.created_at):%H:%M}: {_clip(e.text)}"
                    )
                    meta = [_entry_scores(e)]
                    if e.factors:
                        meta.append("факторы: " + ", ".join(e.factors))
                    if e.emotions:
                        meta.append("эмоции: " + ", ".join(e.emotions))
                    for s in e.spheres:
                        note = "; ".join(
                            x for x in (s.good and f"+ {s.good}", s.bad and f"− {s.bad}") if x
                        )
                        meta.append(
                            f"{titles.get(s.goal_id, 'цель в архиве')}"
                            + (f" {s.score}/10" if s.score else "")
                            + (f" ({note})" if note else "")
                        )
                    meta = [m for m in meta if m]
                    if meta:
                        lines.append("  " + " | ".join(meta))
            return "\n".join(lines)

        return await self._run(work)

    async def get_sleep(self, days: int = 14) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            result = await sleep.overview(session, user, max(1, min(days, 366)), now)
            s = result.stats
            lines = [f"Норма сна {_h(result.goal_min)}. Сон относится к дню пробуждения."]
            if not s.days:
                return lines[0] + "\nЗа этот период сна не записано."
            lines += [
                f"За {days} дн. записан {s.days} дн.: в среднем {_h(s.avg_total_min)} "
                f"(ночь {_h(s.avg_night_min)}, днём {_h(s.avg_nap_min)}); "
                f"отбой {_clock(s.avg_bedtime)}"
                + (f" ± {s.bedtime_spread_min} мин" if s.bedtime_spread_min is not None else "")
                + f", подъём {_clock(s.avg_wake)}; выспался {s.goal_met} из {s.days}; "
                f"недосып {_h(s.debt_min)}; качество {s.avg_quality or '—'}/10.",
                f"Не выспался ({s.short.days} дн.): состояние {s.short.state or '—'}, "
                f"фокус {_h(s.short.focus_min)}. Выспался ({s.enough.days} дн.): "
                f"состояние {s.enough.state or '—'}, фокус {_h(s.enough.focus_min)}.",
                "",
            ]
            for d in result.days:
                parts = [
                    f"{'ночь' if x.kind == SleepKind.NIGHT else 'днём'} "
                    f"{sleep.to_local(user, x.started_at):%H:%M}–"
                    f"{sleep.to_local(user, x.ended_at):%H:%M}"
                    + (f" (качество {x.quality})" if x.quality else "")
                    + (f" — {x.note}" if x.note else "")
                    for x in d.sessions
                ]
                lines.append(f"{_day(d.day)}: {_h(d.total_min)} — " + "; ".join(parts))
            return "\n".join(lines)

        return await self._run(work)

    async def get_review(self, kind: str = "week", offset: int = 0) -> str:
        try:
            period_kind = PeriodKind(kind)
        except ValueError:
            raise AdvisorError("kind — week или month") from None

        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            result = await review.build_review(session, user, period_kind, max(offset, 0), now)
            text = f"# Итоги: {review.period_text(result)}\n\n{review.digest(result)}"
            if result.analysis is not None:
                a = result.analysis
                text += f"\n\n## Сохранённый разбор агентом\n{a.summary}\n" + "\n".join(
                    f"- фокус дальше: {step}" for step in a.next_steps
                )
            return text

        return await self._run(work)

    async def search(self, query: str) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            result = await search.search(session, user, query)
            lines = []
            for hit in result.tasks[:20]:
                line = _task_line(hit.task)
                if hit.snippet:
                    line += f" — нашлось в «{hit.where}»: {hit.snippet}"
                lines.append(line)
            for e in result.entries[:20]:
                lines.append(
                    f"дневник #{e.id}, {_day(e.logical_date)}: {e.summary or _clip(e.text, 300)}"
                )
            return "\n".join(lines) or "Ничего не нашлось."

        return await self._run(work)

    # Действия

    async def create_task(
        self,
        title: str,
        expected_result: str,
        estimate_min: int,
        value_mult: float = 1.0,
        goal_id: int | None = None,
        planned_for: date | None = None,
        why: str = "",
    ) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            fields = tasks.normalize_draft(
                TaskDraft(
                    title=title,
                    expected_result=expected_result,
                    goal_id=goal_id,
                    estimate_min=estimate_min,
                    # Ближайший множитель со шкалы: модель может прислать 1.3.
                    value_mult=min(VALUE_MULTIPLIERS, key=lambda m: abs(m - value_mult)),
                    mult_reason=why,
                ),
                await goals.active_goal_ids(session, user),
            )
            task = await tasks.create_draft(
                session, user, fields, f"{SOURCE_MARK} {title}", agent_call_id=None
            )
            tasks.save_task(task)
            if planned_for is not None:
                try:
                    plan.schedule(task, planned_for, user_logical_date(user, now))
                except plan.PlanError:
                    raise AdvisorError(
                        "Задачу можно поставить с сегодня и до 60 дней вперёд."
                    ) from None
            await session.flush()
            task = await tasks.get_task(session, user, task.id)
            assert task is not None
            return f"Создана задача в бэклоге: {_task_line(task)}"

        return await self._run(work)

    async def schedule_task(self, task_id: int, day: date | None) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            task = await tasks.get_task(session, user, task_id)
            if task is None:
                raise AdvisorError(f"Задачи #{task_id} нет.")
            try:
                plan.schedule(task, day, user_logical_date(user, now))
            except plan.PlanError:
                raise AdvisorError(
                    "Планировать можно только задачи в бэклоге или в работе, "
                    "с сегодня и до 60 дней вперёд."
                ) from None
            return f"#{task.id} «{task.title}» — " + (
                f"на {_day(day)}" if day else "без дня, в бэклоге"
            )

        return await self._run(work)

    async def add_diary_entry(self, text: str, analyze: bool = True) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            # Без агента запись сохраняется неразобранной: оценки поставишь в вебе.
            analyze_now = analyze and self._agent is not None
            try:
                outcome = await diary.add_entry(
                    session,
                    self._agent,  # type: ignore[arg-type]
                    user,
                    text,
                    now,
                    analyze=analyze_now,
                )
            except diary.DiaryError:
                raise AdvisorError("Пустую запись не сохранить.") from None
            e = outcome.entry
            result = f"Запись #{e.id} сохранена, +{outcome.xp} XP."
            if e.summary or _entry_scores(e):
                result += f" Разбор: {e.summary or ''} [{_entry_scores(e)}]"
            if outcome.agent_failed:
                result += " Агент не разобрал запись — её можно разобрать позже в вебе."
            return result

        return await self._run(work)

    async def remember(self, text: str) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            try:
                note = await memory.add_note(session, user, text)
            except memory.AdvisorError as exc:
                raise AdvisorError(str(exc)) from None
            return f"Запомнил (#{note.id}): {note.text}"

        return await self._run(work)

    async def forget(self, note_id: int) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            if not await memory.delete_note(session, user, note_id):
                raise AdvisorError(f"Заметки #{note_id} нет.")
            return f"Забыл заметку #{note_id}."

        return await self._run(work)

    async def log_sleep(
        self,
        start: datetime,
        end: datetime,
        kind: Literal["night", "nap"] = "night",
        quality: int | None = None,
        note: str | None = None,
    ) -> str:
        async def work(session: AsyncSession, user: User, now: datetime) -> str:
            data = SleepInput(
                SleepKind(kind),
                start.replace(tzinfo=None),
                end.replace(tzinfo=None),
                quality,
                f"{SOURCE_MARK} {note}" if note else None,
            )
            try:
                item = await sleep.add_session(session, user, data, now)
            except sleep.SleepError as exc:
                raise AdvisorError(str(exc)) from None
            minutes = int((item.ended_at - item.started_at).total_seconds() // 60)
            return f"Записан сон на {_day(item.day)}: {_h(minutes)}."

        return await self._run(work)


# Сервер

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def build_server(advisor: Advisor) -> MCPServer:
    server = MCPServer("deepquest", title="DeepQuest", instructions=INSTRUCTIONS)

    async def call(work: Awaitable[str]) -> str:
        try:
            return await work
        except AdvisorError as exc:
            raise ToolError(str(exc)) from None

    @server.tool(annotations=READ)
    async def overview() -> str:
        """Сводка на сейчас: дата и время, уровень, норма и стрик, таймер, план на сегодня,
        последняя запись дневника, сон за сегодня и список целей с id. Вызывай первым."""
        return await call(advisor.overview())

    @server.tool(annotations=READ)
    async def list_goals() -> str:
        """Цели и направления: «зачем», XP, часы, закрытые задачи, сколько дней без движения."""
        return await call(advisor.list_goals())

    @server.tool(annotations=READ)
    async def list_tasks(
        status: str = "backlog", goal_id: int | None = None, limit: int = 50
    ) -> str:
        """Задачи, свежие сверху. status: backlog (в бэклоге), work (таймер или ждёт отчёта),
        done (закрытые), drafts (черновики), all. goal_id — цель (с её направлениями)
        или направление."""
        return await call(advisor.list_tasks(status, goal_id, limit))

    @server.tool(annotations=READ)
    async def get_task(task_id: int) -> str:
        """Карточка задачи: результат, оценка, множитель, исходная мысль, отчёт и вердикт."""
        return await call(advisor.get_task(task_id))

    @server.tool(annotations=READ)
    async def get_plan(days: int = 7) -> str:
        """План по дням вперёд (до 14): задачи, нагрузка против нормы, просроченное."""
        return await call(advisor.get_plan(days))

    @server.tool(annotations=READ)
    async def get_diary(days: int = 7, goal_id: int | None = None) -> str:
        """Дневник за последние дни (до 120): записи с оценками 1–10, факторами, эмоциями
        и заметками по сферам, рядом фокус и XP дня. goal_id — только записи про эту цель."""
        return await call(advisor.get_diary(days, goal_id))

    @server.tool(annotations=READ)
    async def get_sleep(days: int = 14) -> str:
        """Сон за последние дни: каждый отрезок, средние, отбой и подъём, недосып, качество,
        состояние и фокус в дни недосыпа и когда выспался."""
        return await call(advisor.get_sleep(days))

    @server.tool(annotations=READ)
    async def get_review(kind: str = "week", offset: int = 0) -> str:
        """Итоги недели (kind=week, пн–вс) или месяца (month); offset — сколько периодов назад.
        Работа против того же отрезка прошлого периода, сферы, сон, плохие и хорошие дни."""
        return await call(advisor.get_review(kind, offset))

    @server.tool(annotations=READ)
    async def search(query: str) -> str:
        """Поиск по задачам (название, результат, уточнение, отчёты) и дневнику: все слова
        запроса, без учёта регистра."""
        return await call(advisor.search(query))

    @server.tool(annotations=WRITE)
    async def create_task(
        title: str,
        expected_result: str,
        estimate_min: int,
        value_mult: float = 1.0,
        goal_id: int | None = None,
        planned_for: date | None = None,
        why: str = "",
    ) -> str:
        """Завести задачу сразу в бэклог. title — действие с глагола; expected_result —
        проверяемый результат; estimate_min — минуты (5–480); value_mult — ценность:
        0.5 рутина, 0.7 изучение, 1 обычная работа, 1.2 осязаемый результат, 1.5 шаг вовне,
        2 ключевой рискованный шаг; why — почему такой множитель; goal_id — цель
        или направление; planned_for — день (YYYY-MM-DD) или пусто."""
        return await call(
            advisor.create_task(
                title, expected_result, estimate_min, value_mult, goal_id, planned_for, why
            )
        )

    @server.tool(annotations=WRITE)
    async def schedule_task(task_id: int, day: date | None = None) -> str:
        """Поставить задачу на день (YYYY-MM-DD) или убрать из плана (day пустой)."""
        return await call(advisor.schedule_task(task_id, day))

    @server.tool(annotations=WRITE)
    async def add_diary_entry(text: str, analyze: bool = True) -> str:
        """Запись в дневник словами пользователя (+15 XP). analyze — разобрать агентом
        на оценки и теги (около 15 секунд)."""
        return await call(advisor.add_diary_entry(text, analyze))

    @server.tool(annotations=WRITE)
    async def log_sleep(
        start: datetime,
        end: datetime,
        kind: Literal["night", "nap"] = "night",
        quality: int | None = None,
        note: str | None = None,
    ) -> str:
        """Записать сон. start и end — местное время пользователя (YYYY-MM-DDTHH:MM),
        kind — night (ночной) или nap (дневной), quality — 1–10, как выспался."""
        return await call(advisor.log_sleep(start, end, kind, quality, note))

    @server.tool(annotations=WRITE)
    async def remember(text: str) -> str:
        """Запомнить о пользователе что-то устойчивое и полезное на будущее — одной фразой:
        предпочтение, ограничение, договорённость. Память подмешивается в каждый разговор."""
        return await call(advisor.remember(text))

    @server.tool(annotations=WRITE)
    async def forget(note_id: int) -> str:
        """Забыть заметку из памяти по её номеру (#id), если она устарела или неверна."""
        return await call(advisor.forget(note_id))

    return server


def main(args: list[str]) -> int:
    """`deepquest mcp`: сервер на stdio. В stdout идёт только протокол, логи — в stderr."""
    from deepquest.agent.setup import build_agent
    from deepquest.config import Settings
    from deepquest.db.migrate import upgrade_database
    from deepquest.db.session import create_engine, create_sessionmaker

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    settings = Settings()
    if not settings.allowed_telegram_ids:
        print("ALLOWED_TELEGRAM_IDS пуст: не знаю, чьи данные показывать.", file=sys.stderr)
        return 1
    upgrade_database(settings.database_path)
    engine = create_engine(settings.database_path)
    handle = build_agent(settings)
    advisor = Advisor(create_sessionmaker(engine), settings.allowed_telegram_ids[0], handle.agent)
    server = build_server(advisor)
    # Движок и агент живут до конца процесса: клиент закрывает stdin — процесс выходит.
    server.run("stdio")
    return 0
