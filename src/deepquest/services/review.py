"""Итоги периода — недели (пн–вс) или месяца — по логическим дням пользователя.

Цифры считаются на лету из журнала XP (там же засчитанные минуты) и дневника.
Сравниваем с тем же отрезком прошлого периода: если неделя идёт третий день, то с первыми
тремя днями прошлой недели, иначе незаконченная неделя всегда проигрывала бы законченной.

Плохие и хорошие дни — по среднему состоянию дня (настроение, энергия и желание вместе):
ниже BAD_BELOW — плохой, от GOOD_FROM — хороший. Для них видно, сколько было работы и какие
факторы встречались, — отсюда и растут выводы «в дни с плохим сном фокус вдвое меньше».

Текст разбора пишет агент по кнопке; он хранится в `reviews`, повторный разбор перезаписывает.
"""

import calendar
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.base import AgentError, TaskAgent
from deepquest.agent.schemas import ReviewAnalysis, ReviewContext
from deepquest.db.models import (
    DayStats,
    DayStatus,
    DiaryEntry,
    DiarySphere,
    Goal,
    Review,
    Task,
    TaskStatus,
    User,
    XpEvent,
    XpKind,
)
from deepquest.services import goals as goals_service
from deepquest.services import sleep as sleep_service
from deepquest.services import xp
from deepquest.services.agent_log import record_calls
from deepquest.services.days import user_logical_date
from deepquest.services.diary import MONTHS, PARTS_OF_DAY
from deepquest.services.planning import goal_context
from deepquest.services.sleep import SleepStats

logger = logging.getLogger(__name__)

BAD_BELOW = 5.0
GOOD_FROM = 7.0
TOP_FACTORS = 5
TOP_TASKS = 5
NOTES_PER_SPHERE = 3
# Сколько записей и задач уходит агенту: больше ему не нужно, а промпт растёт.
DIGEST_ENTRIES = 60
DIGEST_TASKS = 40
DIGEST_TEXT_LEN = 300

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]  # fmt: skip


class PeriodKind(StrEnum):
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class Period:
    kind: PeriodKind
    first: date
    last: date

    @property
    def label(self) -> str:
        if self.kind == PeriodKind.MONTH:
            return f"{MONTH_NAMES[self.first.month - 1]} {self.first.year}"
        first, last = self.first, self.last
        if first.month == last.month:
            return f"{first.day}–{last.day} {MONTHS[last.month - 1]}"
        return f"{first.day} {MONTHS[first.month - 1]} – {last.day} {MONTHS[last.month - 1]}"

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def period_of(kind: PeriodKind, today: date, offset: int = 0) -> Period:
    """Период, в который попадает `today`, или `offset` периодов назад."""
    if kind == PeriodKind.WEEK:
        monday = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
        return Period(kind, monday, monday + timedelta(days=6))
    month_index = today.year * 12 + today.month - 1 - offset
    year, month = divmod(month_index, 12)
    first = date(year, month + 1, 1)
    return Period(kind, first, first.replace(day=calendar.monthrange(year, month + 1)[1]))


def previous(period: Period) -> Period:
    return period_of(period.kind, period.first - timedelta(days=1))


@dataclass(frozen=True)
class Totals:
    xp: int
    minutes: int
    done_tasks: int
    entries: int
    # Закрытые дни: норма выполнена / все, кроме паузы.
    norm_met: int
    norm_days: int


@dataclass(frozen=True)
class State:
    mood: float | None
    energy: float | None
    drive: float | None


@dataclass(frozen=True)
class SphereReview:
    goal_id: int
    title: str
    xp: int
    prev_xp: int
    minutes: int
    done_tasks: int
    # Средняя оценка сферы в дневнике за период и за тот же отрезок прошлого.
    score: float | None
    prev_score: float | None
    mentions: int
    good: list[str]
    bad: list[str]


@dataclass(frozen=True)
class DayPoint:
    day: date
    # Среднее состояние дня: настроение, энергия и желание вместе; None — записей нет.
    state: float | None
    focus_min: int
    xp: int
    status: DayStatus | None
    # Сколько спал перед этим днём и днём; None — сон не записан.
    sleep_min: int | None = None


@dataclass(frozen=True)
class DayGroup:
    """Плохие или хорошие дни: сколько их, сколько в них было работы и что их сопровождало."""

    days: int
    focus_min: float | None
    xp: float | None
    factors: list[tuple[str, int]]


@dataclass(frozen=True)
class TopTask:
    id: int
    title: str
    goal_id: int | None
    xp: int


@dataclass
class PeriodReview:
    period: Period
    # Последний учтённый день: сегодня, если период ещё идёт.
    end: date
    totals: Totals
    prev_totals: Totals
    state: State
    prev_state: State
    spheres: list[SphereReview]
    days: list[DayPoint]
    bad_days: DayGroup
    good_days: DayGroup
    emotions: list[tuple[str, int]]
    factors: list[tuple[str, int]]
    top_tasks: list[TopTask]
    sleep: SleepStats
    prev_sleep: SleepStats
    sleep_goal_min: int
    analysis: ReviewAnalysis | None = None
    analyzed_at: datetime | None = None
    # Только для разбора агентом: что сделано и что писал.
    done_titles: list[str] = field(default_factory=list)
    entries: list[DiaryEntry] = field(default_factory=list)

    @property
    def in_progress(self) -> bool:
        return self.end < self.period.last


def _average(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _scores(entry: DiaryEntry) -> list[int]:
    return [v for v in (entry.mood, entry.energy, entry.drive) if v is not None]


async def _roots(session: AsyncSession, user: User) -> dict[int, int]:
    """id цели или направления → id цели верхнего уровня (включая архивные)."""
    rows = await session.execute(select(Goal.id, Goal.parent_id).where(Goal.user_id == user.id))
    return {goal_id: parent_id or goal_id for goal_id, parent_id in rows}


async def _minutes(
    session: AsyncSession, user: User, first: date, last: date
) -> tuple[dict[date, float], dict[int | None, float]]:
    """Засчитанные минуты закрытых задач по дням и по целям за [first, last]."""
    by_day: dict[date, float] = defaultdict(float)
    by_goal: dict[int | None, float] = defaultdict(float)
    for credit in await xp.credits(session, user, first, last):
        by_day[credit.day] += credit.minutes
        by_goal[credit.goal_id] += credit.minutes
    return by_day, by_goal


@dataclass
class _Window:
    """Всё, что нужно про отрезок дней: из него собираются и итоги, и сравнение."""

    xp_by_day: dict[date, int]
    xp_by_goal: dict[int | None, int]
    minutes_by_day: dict[date, float]
    minutes_by_goal: dict[int | None, float]
    done: list[tuple[int, int | None]]  # (task_id, goal_id) закрытых задач
    entries: list[DiaryEntry]
    statuses: dict[date, DayStatus]

    def totals(self) -> Totals:
        closed = [s for s in self.statuses.values() if s != DayStatus.PAUSED]
        return Totals(
            xp=sum(self.xp_by_day.values()),
            minutes=int(sum(self.minutes_by_day.values())),
            done_tasks=len(self.done),
            entries=len(self.entries),
            norm_met=sum(1 for s in closed if s == DayStatus.MET),
            norm_days=len(closed),
        )

    def state(self) -> State:
        return State(
            mood=_average([e.mood for e in self.entries if e.mood is not None]),
            energy=_average([e.energy for e in self.entries if e.energy is not None]),
            drive=_average([e.drive for e in self.entries if e.drive is not None]),
        )


async def _window(
    session: AsyncSession, user: User, first: date, last: date, now: datetime
) -> _Window:
    in_range = (XpEvent.logical_date >= first, XpEvent.logical_date <= last)
    xp_by_day: dict[date, int] = defaultdict(int)
    xp_by_goal: dict[int | None, int] = defaultdict(int)
    for day, goal_id, amount in await session.execute(
        select(XpEvent.logical_date, XpEvent.goal_id, XpEvent.amount).where(
            XpEvent.user_id == user.id, *in_range
        )
    ):
        xp_by_day[day] += amount
        xp_by_goal[goal_id] += amount
    # Задача закрыта в тот день, когда за неё впервые начислили XP, и итог — «готово».
    done_rows = await session.execute(
        select(Task.id, Task.goal_id)
        .join(XpEvent, XpEvent.task_id == Task.id)
        .where(
            XpEvent.user_id == user.id,
            XpEvent.kind == XpKind.TASK,
            Task.status == TaskStatus.DONE,
            *in_range,
        )
    )
    done = [(task_id, goal_id) for task_id, goal_id in done_rows]
    minutes_by_day, minutes_by_goal = await _minutes(session, user, first, last)
    entries = list(
        await session.scalars(
            select(DiaryEntry)
            .where(
                DiaryEntry.user_id == user.id,
                DiaryEntry.logical_date >= first,
                DiaryEntry.logical_date <= last,
            )
            .order_by(DiaryEntry.created_at, DiaryEntry.id)
        )
    )
    status_rows = await session.execute(
        select(DayStats.logical_date, DayStats.status).where(
            DayStats.user_id == user.id,
            DayStats.logical_date >= first,
            DayStats.logical_date <= last,
        )
    )
    statuses = {day: status for day, status in status_rows}
    return _Window(xp_by_day, xp_by_goal, minutes_by_day, minutes_by_goal, done, entries, statuses)


def _by_root[T: (int, float)](values: dict[int | None, T], roots: dict[int, int]) -> dict[int, T]:
    result: dict[int, T] = defaultdict(int)  # type: ignore[arg-type]
    for goal_id, value in values.items():
        if goal_id is not None and goal_id in roots:
            result[roots[goal_id]] += value
    return result


def _sphere_notes(entries: list[DiaryEntry]) -> dict[int, list[DiarySphere]]:
    notes: dict[int, list[DiarySphere]] = defaultdict(list)
    for entry in entries:
        for sphere in entry.spheres:
            notes[sphere.goal_id].append(sphere)
    return notes


def _day_states(entries: list[DiaryEntry]) -> dict[date, float]:
    values: dict[date, list[int]] = defaultdict(list)
    for entry in entries:
        values[entry.logical_date] += _scores(entry)
    return {day: round(mean(scores), 1) for day, scores in values.items() if scores}


def _group(days: list[date], window: _Window, factors_by_day: dict[date, set[str]]) -> DayGroup:
    counter: Counter[str] = Counter()
    for day in days:
        counter.update(factors_by_day.get(day, set()))
    return DayGroup(
        days=len(days),
        focus_min=_average([window.minutes_by_day.get(day, 0) for day in days]),
        xp=_average([window.xp_by_day.get(day, 0) for day in days]),
        factors=counter.most_common(TOP_FACTORS),
    )


async def build_review(
    session: AsyncSession, user: User, kind: PeriodKind, offset: int, now: datetime
) -> PeriodReview:
    today = user_logical_date(user, now)
    period = period_of(kind, today, offset)
    end = min(period.last, today)
    prev = previous(period)
    prev_end = min(prev.first + (end - period.first), prev.last)

    current = await _window(session, user, period.first, end, now)
    before = await _window(session, user, prev.first, prev_end, now)
    sleep_now = sleep_service.by_day(
        user, await sleep_service.sessions_between(session, user, period.first, end)
    )
    sleep_before = sleep_service.by_day(
        user, await sleep_service.sessions_between(session, user, prev.first, prev_end)
    )
    roots = await _roots(session, user)

    xp_now, xp_before = _by_root(current.xp_by_goal, roots), _by_root(before.xp_by_goal, roots)
    minutes_now = _by_root(current.minutes_by_goal, roots)
    done_now: dict[int, int] = defaultdict(int)
    for _, goal_id in current.done:
        if goal_id is not None and goal_id in roots:
            done_now[roots[goal_id]] += 1
    notes_now, notes_before = _sphere_notes(current.entries), _sphere_notes(before.entries)

    def sphere(goal: Goal) -> SphereReview:
        notes = notes_now.get(goal.id, [])
        scores = [n.score for n in notes if n.score is not None]
        prev_scores = [n.score for n in notes_before.get(goal.id, []) if n.score is not None]
        # Свежие заметки — первыми.
        return SphereReview(
            goal_id=goal.id,
            title=goal.title,
            xp=xp_now.get(goal.id, 0),
            prev_xp=xp_before.get(goal.id, 0),
            minutes=int(minutes_now.get(goal.id, 0)),
            done_tasks=done_now.get(goal.id, 0),
            score=_average([float(s) for s in scores]),
            prev_score=_average([float(s) for s in prev_scores]),
            mentions=len(notes),
            good=[n.good for n in reversed(notes) if n.good][:NOTES_PER_SPHERE],
            bad=[n.bad for n in reversed(notes) if n.bad][:NOTES_PER_SPHERE],
        )

    states = _day_states(current.entries)
    days = []
    day = period.first
    while day <= end:
        days.append(
            DayPoint(
                day=day,
                state=states.get(day),
                focus_min=int(current.minutes_by_day.get(day, 0)),
                xp=current.xp_by_day.get(day, 0),
                status=current.statuses.get(day),
                sleep_min=sleep_now[day].total_min if day in sleep_now else None,
            )
        )
        day += timedelta(days=1)

    factors_by_day: dict[date, set[str]] = defaultdict(set)
    emotions: Counter[str] = Counter()
    factors: Counter[str] = Counter()
    for entry in current.entries:
        factors_by_day[entry.logical_date].update(entry.factors)
        emotions.update(entry.emotions)
        factors.update(entry.factors)

    task_xp: dict[int, int] = defaultdict(int)
    done_ids = [task_id for task_id, _ in current.done]
    if done_ids:
        for task_id, amount in await session.execute(
            select(XpEvent.task_id, func.sum(XpEvent.amount))
            .where(XpEvent.task_id.in_(done_ids))
            .group_by(XpEvent.task_id)
        ):
            task_xp[task_id] = amount or 0
    done_tasks = (
        list(await session.scalars(select(Task).where(Task.id.in_(done_ids)))) if done_ids else []
    )
    done_tasks.sort(key=lambda task: -task_xp[task.id])
    top = [
        TopTask(
            task.id,
            task.title,
            roots.get(task.goal_id) if task.goal_id else None,
            task_xp[task.id],
        )
        for task in done_tasks[:TOP_TASKS]
    ]

    saved = await session.scalar(
        select(Review).where(
            Review.user_id == user.id, Review.kind == kind, Review.first_day == period.first
        )
    )
    return PeriodReview(
        period=period,
        end=end,
        totals=current.totals(),
        prev_totals=before.totals(),
        state=current.state(),
        prev_state=before.state(),
        sleep=await sleep_service.stats(session, user, sleep_now, period.first, end, now),
        prev_sleep=await sleep_service.stats(
            session, user, sleep_before, prev.first, prev_end, now
        ),
        sleep_goal_min=user.sleep_goal_min,
        spheres=[sphere(goal) for goal in await goals_service.list_goals(session, user)],
        days=days,
        bad_days=_group([d for d, s in states.items() if s < BAD_BELOW], current, factors_by_day),
        good_days=_group([d for d, s in states.items() if s >= GOOD_FROM], current, factors_by_day),
        emotions=emotions.most_common(TOP_FACTORS),
        factors=factors.most_common(TOP_FACTORS),
        top_tasks=top,
        analysis=ReviewAnalysis.model_validate(saved.data) if saved else None,
        analyzed_at=saved.created_at if saved else None,
        done_titles=[task.title for task in done_tasks],
        entries=current.entries,
    )


# Разбор агентом


def _signed(value: float) -> str:
    return f"+{value:g}" if value > 0 else f"{value:g}"


def _vs(now: float | None, before: float | None) -> str:
    if now is None:
        return "—"
    if before is None:
        return f"{now:g}"
    return f"{now:g} (было {before:g}, {_signed(round(now - before, 1))})"


def _hours(minutes: float | None) -> str:
    return "—" if minutes is None else f"{minutes / 60:.1f} ч"


def _factor_list(items: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ×{count}" for name, count in items) or "—"


def _clock(minutes: int | None) -> str:
    return "—" if minutes is None else f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sleep_digest(review: PeriodReview) -> list[str]:
    s, p = review.sleep, review.prev_sleep
    lines = [f"## Сон (норма {_hours(review.sleep_goal_min)}, сон относится к дню пробуждения)"]
    if not s.days:
        return [*lines, "- сон не записан"]
    lines += [
        f"- Записан за {s.days} дн.; в среднем {_hours(s.avg_total_min)} "
        f"(было {_hours(p.avg_total_min)}), из них днём {_hours(s.avg_nap_min)}",
        f"- Отбой в среднем {_clock(s.avg_bedtime)}"
        + (f" ± {s.bedtime_spread_min} мин" if s.bedtime_spread_min is not None else "")
        + f", подъём {_clock(s.avg_wake)}",
        f"- Выспался {s.goal_met} из {s.days} дн., недосып за период {_hours(s.debt_min)}",
        f"- Качество сна: {_vs(s.avg_quality, p.avg_quality)}",
    ]
    for title, group in (("Не выспался", s.short), ("Выспался", s.enough)):
        if group.days:
            lines.append(
                f"- {title} ({group.days} дн.): состояние {group.state or '—'}, "
                f"фокус {_hours(group.focus_min)}"
            )
    return lines


def digest(review: PeriodReview) -> str:
    """Итоги периода текстом для агента."""
    t, p = review.totals, review.prev_totals
    lines = [
        "## Работа (в скобках — тот же отрезок прошлого периода)",
        f"- XP: {_vs(t.xp, p.xp)}",
        f"- Фокус (засчитано по задачам): {_hours(t.minutes)} (было {_hours(p.minutes)})",
        f"- Закрыто задач: {_vs(t.done_tasks, p.done_tasks)}",
        f"- Норма выполнена: {t.norm_met} из {t.norm_days} закрытых дней",
        f"- Записей в дневнике: {_vs(t.entries, p.entries)}",
        "",
        "## Состояние, среднее за период (1–10)",
        f"- Настроение: {_vs(review.state.mood, review.prev_state.mood)}",
        f"- Энергия: {_vs(review.state.energy, review.prev_state.energy)}",
        f"- Желание действовать: {_vs(review.state.drive, review.prev_state.drive)}",
        "",
        *_sleep_digest(review),
        "",
        "## Сферы",
    ]
    for s in review.spheres:
        line = (
            f"- {s.title}: XP {_vs(s.xp, s.prev_xp)}, фокус {_hours(s.minutes)}, "
            f"задач {s.done_tasks}, оценка в дневнике {_vs(s.score, s.prev_score)}"
        )
        if s.good:
            line += "; радует: " + "; ".join(s.good)
        if s.bad:
            line += "; огорчает: " + "; ".join(s.bad)
        lines.append(line)
    for title, group in (("Плохие дни", review.bad_days), ("Хорошие дни", review.good_days)):
        lines += [
            "",
            f"## {title} (среднее состояние {'ниже 5' if title == 'Плохие дни' else 'от 7'})",
            f"- Дней: {group.days}; в среднем фокус {_hours(group.focus_min)}, "
            f"XP {group.xp if group.xp is not None else '—'}",
            f"- Факторы: {_factor_list(group.factors)}",
        ]
    lines += [
        "",
        f"## Частые эмоции: {_factor_list(review.emotions)}",
        f"## Частые факторы: {_factor_list(review.factors)}",
        "",
        "## Сделанные задачи (по XP)",
    ]
    lines += [f"- {title}" for title in review.done_titles[:DIGEST_TASKS]] or ["- нет"]
    lines += ["", "## Записи дневника"]
    for entry in review.entries[-DIGEST_ENTRIES:]:
        text = entry.summary or " ".join(entry.text.split())[:DIGEST_TEXT_LEN]
        scores = ", ".join(
            f"{name} {value}"
            for name, value in (
                ("настр.", entry.mood),
                ("энергия", entry.energy),
                ("желание", entry.drive),
            )
            if value is not None
        )
        tags = ", ".join(entry.factors)
        lines.append(
            f"- {entry.logical_date:%d.%m} ({PARTS_OF_DAY[entry.part_of_day]}): {text}"
            + (f" [{scores}]" if scores else "")
            + (f" факторы: {tags}" if tags else "")
        )
    if not review.entries:
        lines.append("- нет")
    return "\n".join(lines)


def period_text(review: PeriodReview) -> str:
    name = "неделя" if review.period.kind == PeriodKind.WEEK else "месяц"
    text = f"{name} {review.period.label}"
    if review.in_progress:
        passed = (review.end - review.period.first).days + 1
        text += f" (идёт: прошло {passed} дн. из {review.period.days})"
    return text


async def analyze(
    session: AsyncSession, agent: TaskAgent, user: User, review: PeriodReview, now: datetime
) -> bool:
    """Разбор агентом; False — агент недоступен. Сохранённый разбор перезаписывается."""
    context = ReviewContext(
        period=period_text(review),
        digest=digest(review),
        goals=tuple(await goal_context(session, user)),
    )
    await session.commit()
    try:
        result = await agent.review_period(context)
    except AgentError as exc:
        logger.warning("review_period failed: %s", exc)
        await record_calls(session, user, exc.calls)
        return False
    call_id = await record_calls(session, user, result.calls)
    saved = await session.scalar(
        select(Review).where(
            Review.user_id == user.id,
            Review.kind == review.period.kind,
            Review.first_day == review.period.first,
        )
    )
    if saved is None:
        saved = Review(user_id=user.id, kind=review.period.kind, first_day=review.period.first)
        session.add(saved)
    saved.data = result.output.model_dump()
    saved.agent_call_id = call_id
    saved.created_at = now
    await session.flush()
    review.analysis = result.output
    review.analyzed_at = now
    return True
