"""Таймер задач. Время — метки в БД, а не счётчик в памяти: сон Mac и перезапуск ему не мешают.

Таймеров может идти несколько сразу — по одному на задачу: работа бывает параллельной.
Время по таймеру — факт для истории: XP считается от оценки (services/xp.py), а оценку
пользователь правит сам, если задача заняла больше или меньше. Таймер не обязателен.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import Task, TaskStatus, TimeEntry, User


class TimerError(ValueError):
    """Действие с таймером невозможно в текущем статусе задачи."""


@dataclass
class StartResult:
    entry: TimeEntry
    already_running: bool = False


async def running_entries(session: AsyncSession, user: User) -> list[TimeEntry]:
    """Идущие таймеры, первым — запущенный раньше всех."""
    return list(
        await session.scalars(
            select(TimeEntry)
            .where(TimeEntry.user_id == user.id, TimeEntry.ended_at.is_(None))
            .order_by(TimeEntry.started_at, TimeEntry.id)
        )
    )


async def running_entry(session: AsyncSession, task: Task) -> TimeEntry | None:
    """Идущий отрезок задачи, если таймер по ней запущен."""
    return await session.scalar(
        select(TimeEntry).where(TimeEntry.task_id == task.id, TimeEntry.ended_at.is_(None))
    )


async def total_minutes(session: AsyncSession, task: Task, now: datetime) -> int:
    """Сколько минут по таймеру ушло на задачу, включая идущий отрезок."""
    entries = await session.scalars(select(TimeEntry).where(TimeEntry.task_id == task.id))
    seconds = sum(((entry.ended_at or now) - entry.started_at).total_seconds() for entry in entries)
    return max(int(seconds // 60), 0)


def _close(entry: TimeEntry, at: datetime, reason: str) -> None:
    # Время команды может прийти раньше старта (часы, задержка доставки) — не уходим в минус.
    entry.ended_at = max(at, entry.started_at)
    entry.stop_reason = reason


async def start(session: AsyncSession, user: User, task: Task, at: datetime) -> StartResult:
    """Запустить таймер задачи. Другие таймеры идут дальше."""
    if task.status == TaskStatus.RUNNING:
        entry = await running_entry(session, task)
        if entry is not None:
            return StartResult(entry, already_running=True)
    if task.status not in {TaskStatus.OPEN, TaskStatus.RUNNING}:
        raise TimerError(f"Task {task.id} is {task.status}")
    if not task.is_estimated:
        raise TimerError(f"Task {task.id} has no estimate")
    entry = TimeEntry(user_id=user.id, task_id=task.id, started_at=at)
    session.add(entry)
    task.status = TaskStatus.RUNNING
    await session.flush()
    return StartResult(entry)


async def pause(session: AsyncSession, task: Task, at: datetime) -> None:
    entry = await running_entry(session, task)
    if task.status != TaskStatus.RUNNING or entry is None:
        raise TimerError(f"Task {task.id} is not running")
    _close(entry, at, "manual")
    task.status = TaskStatus.OPEN


async def finish(session: AsyncSession, task: Task, at: datetime) -> None:
    """«Готово»: таймер задачи останавливается, задача ждёт отчёт."""
    if task.status not in {TaskStatus.OPEN, TaskStatus.RUNNING}:
        raise TimerError(f"Task {task.id} is {task.status}")
    if not task.is_estimated:
        raise TimerError(f"Task {task.id} has no estimate")
    entry = await running_entry(session, task)
    if entry is not None:
        _close(entry, at, "done")
    task.status = TaskStatus.AWAITING_REPORT
