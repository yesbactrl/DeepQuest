"""Данные для настраиваемых графиков дашборда.

Любой график описывается `ChartConfig`: что считать (метрика), как группировать по времени
(шаг), за какой период и как делить на серии (по целям или без разбивки). Один и тот же
ответ годится и для столбцов, и для линий, и для круговой диаграммы.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.db.models import Goal, Task, TaskStatus, TimeEntry, User, XpEvent, XpKind
from deepquest.services.days import split_by_day, user_day_bounds, user_logical_date
from deepquest.services.goals import PALETTE


class Metric(StrEnum):
    MINUTES = "minutes"
    XP = "xp"
    TASKS = "tasks"


class Bucket(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Split(StrEnum):
    NONE = "none"
    GOAL = "goal"


class Period(StrEnum):
    WEEK = "7d"
    MONTH = "30d"
    QUARTER = "90d"
    YEAR = "365d"
    SEASON = "season"


class ChartType(StrEnum):
    BAR = "bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"


class Size(StrEnum):
    HALF = "half"
    FULL = "full"


class ChartConfig(BaseModel):
    title: str = Field(default="График", max_length=80)
    metric: Metric = Metric.MINUTES
    bucket: Bucket = Bucket.DAY
    split: Split = Split.GOAL
    period: Period = Period.MONTH
    chart: ChartType = ChartType.BAR
    size: Size = Size.HALF
    # Только эта цель; разбивка тогда идёт по её направлениям.
    goal_id: int | None = None


METRIC_NAMES = {Metric.MINUTES: "Время", Metric.XP: "XP", Metric.TASKS: "Закрыто задач"}
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
NO_GOAL = "none"
TOTAL = "all"
PERIOD_DAYS = {Period.WEEK: 7, Period.MONTH: 30, Period.QUARTER: 90, Period.YEAR: 365}


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    values: list[float]
    # Постоянный номер цвета: цвет следует за целью, а не за её местом в рейтинге.
    # -1 — нейтральная серия («Без цели»).
    slot: int

    @property
    def total(self) -> float:
        return sum(self.values)


@dataclass(frozen=True)
class ChartData:
    buckets: list[str]
    labels: list[str]
    series: list[Series]
    # Дневная норма — чтобы нарисовать линию на графике минут по дням.
    norm_min: int | None


def _first_day(period: Period, today: date) -> date:
    if period == Period.SEASON:
        return today.replace(day=1)
    return today - timedelta(days=PERIOD_DAYS[period] - 1)


def _bucket_of(day: date, bucket: Bucket) -> date:
    if bucket == Bucket.WEEK:
        return day - timedelta(days=day.weekday())
    if bucket == Bucket.MONTH:
        return day.replace(day=1)
    return day


def _label(start: date, bucket: Bucket) -> str:
    if bucket == Bucket.MONTH:
        return f"{MONTHS[start.month - 1]} {start:%Y}"
    if bucket == Bucket.WEEK:
        return f"с {start:%d.%m}"
    return f"{start:%d.%m}"


def _buckets(first: date, last: date, bucket: Bucket) -> list[date]:
    result: list[date] = []
    day = first
    while day <= last:
        key = _bucket_of(day, bucket)
        if not result or result[-1] != key:
            result.append(key)
        day += timedelta(days=1)
    return result


class _SeriesMap:
    """Куда относить задачу или начисление: к какой серии графика."""

    def __init__(self, goals: list[Goal], config: ChartConfig) -> None:
        self._config = config
        self.names: dict[str, str] = {}
        self.slots: dict[str, int] = {TOTAL: 0, NO_GOAL: -1}
        self._key_of: dict[int, str] = {}
        if config.split == Split.NONE:
            self.names[TOTAL] = METRIC_NAMES[config.metric]
        by_id = {goal.id: goal for goal in goals}
        for goal in sorted(goals, key=lambda g: g.id):
            root = by_id.get(goal.parent_id) if goal.parent_id else goal
            if root is None:
                continue
            if config.goal_id is not None:
                # График одной цели: серии — её направления, плюс задачи на самой цели.
                if root.id != config.goal_id:
                    continue
                key = f"goal:{goal.id}"
                name = goal.title if goal.parent_id else f"{goal.title} (без направления)"
            else:
                key = f"goal:{root.id}"
                name = root.title
            self._key_of[goal.id] = key
            if config.goal_id is None and root.color in PALETTE:
                # Цель на графиках того же цвета, что её стат на странице «Персонаж».
                self.slots.setdefault(key, PALETTE.index(root.color))
            else:
                self.slots.setdefault(key, len(self.slots) - 2)
            if config.split == Split.GOAL:
                self.names.setdefault(key, name)

    def key(self, goal_id: int | None) -> str | None:
        """Серия для цели задачи; None — данные в этот график не входят."""
        if self._config.goal_id is not None and goal_id not in self._key_of:
            return None
        if self._config.split == Split.NONE:
            return TOTAL
        if goal_id is None:
            self.names.setdefault(NO_GOAL, "Без цели")
            return NO_GOAL
        return self._key_of.get(goal_id)


async def chart_data(
    session: AsyncSession, user: User, config: ChartConfig, now: datetime
) -> ChartData:
    today = user_logical_date(user, now)
    first = _first_day(config.period, today)
    buckets = _buckets(first, today, config.bucket)
    index = {start: i for i, start in enumerate(buckets)}
    goals = list(
        await session.scalars(
            select(Goal).where(Goal.user_id == user.id).options(selectinload(Goal.parent))
        )
    )
    series_map = _SeriesMap(goals, config)
    values: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(buckets))

    def add(day: date, goal_id: int | None, amount: float) -> None:
        key = series_map.key(goal_id)
        if key is not None and first <= day <= today:
            values[key][index[_bucket_of(day, config.bucket)]] += amount

    if config.metric == Metric.MINUTES:
        start, _ = user_day_bounds(user, first)
        _, end = user_day_bounds(user, today)
        rows = await session.execute(
            select(Task.goal_id, TimeEntry.started_at, TimeEntry.ended_at)
            .join(Task, Task.id == TimeEntry.task_id)
            .where(
                TimeEntry.user_id == user.id,
                TimeEntry.started_at < end,
                or_(TimeEntry.ended_at.is_(None), TimeEntry.ended_at > start),
            )
        )
        for goal_id, started_at, ended_at in rows:
            for day, seconds in split_by_day(
                user, max(started_at, start), min(ended_at or now, end)
            ):
                add(day, goal_id, seconds / 60)
    else:
        query = select(XpEvent.logical_date, XpEvent.goal_id, XpEvent.amount).where(
            XpEvent.user_id == user.id,
            XpEvent.logical_date >= first,
            XpEvent.logical_date <= today,
        )
        if config.metric == Metric.TASKS:
            # Задача закрыта, когда за неё впервые начислили XP и итог — «готово».
            query = query.join(Task, Task.id == XpEvent.task_id).where(
                XpEvent.kind == XpKind.TASK, Task.status == TaskStatus.DONE
            )
        for day, goal_id, amount in await session.execute(query):
            add(day, goal_id, 1 if config.metric == Metric.TASKS else amount)

    series = [
        Series(
            key, series_map.names[key], [round(v, 1) for v in values[key]], series_map.slots[key]
        )
        for key in series_map.names
    ]
    if config.split == Split.GOAL:
        # Пустые серии не рисуем; «Без цели» — в конце.
        series = sorted(
            (s for s in series if s.total),
            key=lambda s: (s.key == NO_GOAL, -s.total),
        )
    norm = (
        user.daily_norm_min
        if config.metric == Metric.MINUTES and config.bucket == Bucket.DAY
        else None
    )
    return ChartData(
        buckets=[start.isoformat() for start in buckets],
        labels=[_label(start, config.bucket) for start in buckets],
        series=series,
        norm_min=norm,
    )
