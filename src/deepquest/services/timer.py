"""Таймер задач. Время — метки в БД, а не счётчик в памяти: сон Mac и перезапуск ему не мешают."""

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
    # Задача, которая шла до этого и встала на паузу.
    paused: Task | None = None
    already_running: bool = False


async def running_entry(session: AsyncSession, user: User) -> TimeEntry | None:
    return await session.scalar(
        select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.ended_at.is_(None))
    )


async def _entries(session: AsyncSession, task: Task) -> list[TimeEntry]:
    return list(await session.scalars(select(TimeEntry).where(TimeEntry.task_id == task.id)))


async def total_minutes(session: AsyncSession, task: Task, now: datetime) -> int:
    """Сколько минут ушло на задачу, включая идущий отрезок."""
    seconds = sum(
        ((entry.ended_at or now) - entry.started_at).total_seconds()
        for entry in await _entries(session, task)
    )
    return max(int(seconds // 60), 0)


def _close(entry: TimeEntry, at: datetime, reason: str) -> None:
    # Время команды может прийти раньше старта (часы, задержка доставки) — не уходим в минус.
    entry.ended_at = max(at, entry.started_at)
    entry.stop_reason = reason


async def start(session: AsyncSession, user: User, task: Task, at: datetime) -> StartResult:
    if task.status == TaskStatus.RUNNING:
        entry = await running_entry(session, user)
        if entry is not None and entry.task_id == task.id:
            return StartResult(entry, already_running=True)
    if task.status not in {TaskStatus.OPEN, TaskStatus.RUNNING}:
        raise TimerError(f"Task {task.id} is {task.status}")
    if not task.is_estimated:
        raise TimerError(f"Task {task.id} has no estimate")

    paused = None
    current = await running_entry(session, user)
    if current is not None:
        _close(current, at, "switched")
        paused = await session.get(Task, current.task_id)
        if paused is not None:
            paused.status = TaskStatus.OPEN
        # Без flush частичный уникальный индекс увидит два открытых отрезка сразу.
        await session.flush()

    entry = TimeEntry(user_id=user.id, task_id=task.id, started_at=at)
    session.add(entry)
    task.status = TaskStatus.RUNNING
    await session.flush()
    return StartResult(entry, paused=paused)


async def pause(session: AsyncSession, user: User, task: Task, at: datetime) -> None:
    entry = await running_entry(session, user)
    if task.status != TaskStatus.RUNNING or entry is None or entry.task_id != task.id:
        raise TimerError(f"Task {task.id} is not running")
    _close(entry, at, "manual")
    task.status = TaskStatus.OPEN


async def finish(session: AsyncSession, user: User, task: Task, at: datetime) -> None:
    """«Готово»: таймер останавливается, задача ждёт отчёт."""
    if task.status not in {TaskStatus.OPEN, TaskStatus.RUNNING}:
        raise TimerError(f"Task {task.id} is {task.status}")
    if not task.is_estimated:
        raise TimerError(f"Task {task.id} has no estimate")
    entry = await running_entry(session, user)
    if entry is not None and entry.task_id == task.id:
        _close(entry, at, "done")
    task.status = TaskStatus.AWAITING_REPORT
