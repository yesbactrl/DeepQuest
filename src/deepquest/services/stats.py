"""Статистика для веба: сколько времени и XP ушло на каждую цель и когда она двигалась."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import Goal, Task, TaskStatus, TimeEntry, User, XpEvent
from deepquest.services.days import user_logical_date


@dataclass(frozen=True)
class GoalStats:
    minutes: int
    xp: int
    done_tasks: int
    last_activity_at: datetime | None
    # Сколько логических дней цель стоит без движения (с последней работы или с создания).
    idle_days: int


@dataclass
class _Totals:
    seconds: float = 0
    xp: int = 0
    done_tasks: int = 0
    last_activity_at: datetime | None = None

    def touch(self, moment: datetime) -> None:
        if self.last_activity_at is None or moment > self.last_activity_at:
            self.last_activity_at = moment

    def add(self, other: _Totals) -> None:
        self.seconds += other.seconds
        self.xp += other.xp
        self.done_tasks += other.done_tasks
        if other.last_activity_at is not None:
            self.touch(other.last_activity_at)


async def goal_stats(
    session: AsyncSession, user: User, goals: list[Goal], now: datetime
) -> dict[int, GoalStats]:
    """Статистика по целям и направлениям. Цифры цели включают её направления.

    `goals` — цели верхнего уровня с подгруженными направлениями (`goals.list_goals`).
    """
    totals: dict[int, _Totals] = defaultdict(_Totals)

    entries = await session.execute(
        select(Task.goal_id, TimeEntry.started_at, TimeEntry.ended_at)
        .join(Task, Task.id == TimeEntry.task_id)
        .where(TimeEntry.user_id == user.id, Task.goal_id.is_not(None))
    )
    for goal_id, started_at, ended_at in entries:
        end = ended_at or now
        totals[goal_id].seconds += max((end - started_at).total_seconds(), 0)
        totals[goal_id].touch(end)

    xp_rows = await session.execute(
        select(XpEvent.goal_id, func.sum(XpEvent.amount), func.max(XpEvent.created_at))
        .where(XpEvent.user_id == user.id, XpEvent.goal_id.is_not(None))
        .group_by(XpEvent.goal_id)
    )
    for goal_id, amount, last_at in xp_rows:
        totals[goal_id].xp += amount or 0
        if last_at is not None:
            totals[goal_id].touch(last_at)

    done_rows = await session.execute(
        select(Task.goal_id, func.count())
        .where(
            Task.user_id == user.id,
            Task.status == TaskStatus.DONE,
            Task.goal_id.is_not(None),
        )
        .group_by(Task.goal_id)
    )
    for goal_id, count in done_rows:
        totals[goal_id].done_tasks += count

    today = user_logical_date(user, now)

    def finish(goal: Goal, total: _Totals) -> GoalStats:
        since = total.last_activity_at or goal.created_at
        return GoalStats(
            minutes=int(total.seconds // 60),
            xp=total.xp,
            done_tasks=total.done_tasks,
            last_activity_at=total.last_activity_at,
            idle_days=max((today - user_logical_date(user, since)).days, 0),
        )

    result: dict[int, GoalStats] = {}
    for goal in goals:
        combined = _Totals()
        combined.add(totals[goal.id])
        for direction in goal.active_children:
            result[direction.id] = finish(direction, totals[direction.id])
            combined.add(totals[direction.id])
        result[goal.id] = finish(goal, combined)
    return result


@dataclass(frozen=True)
class TaskTotals:
    minutes: int
    xp: int
    # Когда запущен идущий отрезок таймера, если он есть.
    running_since: datetime | None


async def task_totals(
    session: AsyncSession, tasks: list[Task], now: datetime
) -> dict[int, TaskTotals]:
    """Минуты по таймеру и XP для набора задач — двумя запросами на весь список."""
    ids = [task.id for task in tasks]
    seconds: dict[int, float] = defaultdict(float)
    running: dict[int, datetime] = {}
    xp_by_task: dict[int, int] = {}
    if ids:
        entries = await session.execute(
            select(TimeEntry.task_id, TimeEntry.started_at, TimeEntry.ended_at).where(
                TimeEntry.task_id.in_(ids)
            )
        )
        for task_id, started_at, ended_at in entries:
            seconds[task_id] += max(((ended_at or now) - started_at).total_seconds(), 0)
            if ended_at is None:
                running[task_id] = started_at
        xp_rows = await session.execute(
            select(XpEvent.task_id, func.sum(XpEvent.amount))
            .where(XpEvent.task_id.in_(ids))
            .group_by(XpEvent.task_id)
        )
        xp_by_task = {task_id: amount or 0 for task_id, amount in xp_rows}
    return {
        task_id: TaskTotals(
            minutes=int(seconds[task_id] // 60),
            xp=xp_by_task.get(task_id, 0),
            running_since=running.get(task_id),
        )
        for task_id in ids
    }
