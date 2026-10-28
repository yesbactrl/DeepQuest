"""Персонаж: цели — это статы, направления — скиллы.

Уровни считаются из журнала XP той же формулой, что общий уровень (services/levels.py).
Начисление относится к направлению или цели задачи (`xp_events.goal_id`): скилл — это XP
направления, стат — XP цели вместе со всеми её направлениями, включая убранные в архив.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.db.models import Goal, GoalStatus, Task, User, XpEvent, XpKind
from deepquest.services import goals, xp
from deepquest.services.days import season_of, user_logical_date
from deepquest.services.levels import Level, level_of
from deepquest.services.summary import Summary, build_summary

# Начисление в самый слабый стат за текущий сезон умножается на это.
WEAK_STAT_MULT = 1.2


@dataclass(frozen=True)
class Skill:
    goal: Goal
    level: Level


@dataclass(frozen=True)
class Stat:
    goal: Goal
    level: Level
    season_xp: int
    skills: list[Skill]
    weakest: bool


@dataclass(frozen=True)
class Award:
    """Последнее начисление: для плашки «✓ Задача · +60 XP общий · +60 Здоровье · +60 Спорт»."""

    kind: XpKind
    amount: int
    task_title: str | None
    stat: str | None
    skill: str | None
    created_at: datetime


@dataclass(frozen=True)
class Character:
    summary: Summary
    stats: list[Stat]
    last_award: Award | None


async def _parents(session: AsyncSession, user: User) -> dict[int, int | None]:
    rows = await session.execute(select(Goal.id, Goal.parent_id).where(Goal.user_id == user.id))
    return {goal_id: parent_id for goal_id, parent_id in rows}


async def _xp_by_goal(
    session: AsyncSession, user: User, season: str | None = None
) -> dict[int, int]:
    query = (
        select(XpEvent.goal_id, func.sum(XpEvent.amount))
        .where(XpEvent.user_id == user.id, XpEvent.goal_id.is_not(None))
        .group_by(XpEvent.goal_id)
    )
    if season is not None:
        query = query.where(XpEvent.season == season)
    rows = await session.execute(query)
    return {goal_id: amount or 0 for goal_id, amount in rows if goal_id is not None}


def _by_stat(by_goal: dict[int, int], parents: dict[int, int | None]) -> dict[int, int]:
    totals: dict[int, int] = defaultdict(int)
    for goal_id, amount in by_goal.items():
        totals[parents.get(goal_id) or goal_id] += amount
    return totals


def _weakest(season_xp: dict[int, int]) -> set[int]:
    """Статы с наименьшим XP за сезон. Пока все наравне (скажем, первого числа),
    отстающего нет: бонус и плашка появляются, когда один стат обогнал другие."""
    if len(season_xp) < 2:
        return set()
    low = min(season_xp.values())
    weakest = {stat for stat, amount in season_xp.items() if amount == low}
    return weakest if len(weakest) < len(season_xp) else set()


async def weakest_stats(session: AsyncSession, user: User, season: str) -> set[int]:
    stat_ids = await session.scalars(
        select(Goal.id).where(
            Goal.user_id == user.id,
            Goal.parent_id.is_(None),
            Goal.status == GoalStatus.ACTIVE,
        )
    )
    totals = _by_stat(await _xp_by_goal(session, user, season), await _parents(session, user))
    return _weakest({stat: totals.get(stat, 0) for stat in stat_ids})


async def weak_mult(session: AsyncSession, user: User, task: Task, now: datetime) -> float:
    """Бонус слабому стату для начисления по задаче. При оспаривании — тот же, что в первый раз:
    пересмотр меняет вердикт, а не то, каким стат был в момент сдачи отчёта."""
    first = await xp.first_event(session, task)
    if first is not None:
        return float(first.breakdown.get("weak_mult", 1.0))
    if task.goal_id is None:
        return 1.0
    parents = await _parents(session, user)
    stat = parents.get(task.goal_id) or task.goal_id
    season = season_of(user_logical_date(user, now))
    return WEAK_STAT_MULT if stat in await weakest_stats(session, user, season) else 1.0


async def _last_award(session: AsyncSession, user: User) -> Award | None:
    event = await session.scalar(
        select(XpEvent)
        .where(XpEvent.user_id == user.id, XpEvent.amount != 0)
        .order_by(XpEvent.id.desc())
        .limit(1)
    )
    if event is None:
        return None
    task = await session.get(Task, event.task_id) if event.task_id is not None else None
    title = task.title if task is not None else None
    if event.kind == XpKind.DIARY:
        title = "Запись в дневник" if event.amount > 0 else "Запись удалена"
    if event.kind == XpKind.SLEEP:
        title = "Сон записан" if event.amount > 0 else "Сон убран"
    goal = (
        await session.scalar(
            select(Goal).where(Goal.id == event.goal_id).options(selectinload(Goal.parent))
        )
        if event.goal_id is not None
        else None
    )
    stat = goal.parent if goal is not None and goal.parent is not None else goal
    return Award(
        kind=event.kind,
        amount=event.amount,
        task_title=title,
        stat=stat.title if stat is not None else None,
        skill=goal.title if goal is not None and goal.parent is not None else None,
        created_at=event.created_at,
    )


async def build_character(session: AsyncSession, user: User, now: datetime) -> Character:
    summary = await build_summary(session, user, now)
    parents = await _parents(session, user)
    all_time = await _xp_by_goal(session, user)
    stat_xp = _by_stat(all_time, parents)
    stat_goals = await goals.list_goals(session, user)
    season_totals = _by_stat(await _xp_by_goal(session, user, summary.season), parents)
    season_xp = {goal.id: season_totals.get(goal.id, 0) for goal in stat_goals}
    weakest = _weakest(season_xp)
    stats = [
        Stat(
            goal=goal,
            level=level_of(stat_xp.get(goal.id, 0)),
            season_xp=season_xp[goal.id],
            skills=[
                Skill(goal=direction, level=level_of(all_time.get(direction.id, 0)))
                for direction in goal.active_children
            ],
            weakest=goal.id in weakest,
        )
        for goal in stat_goals
    ]
    return Character(summary=summary, stats=stats, last_award=await _last_award(session, user))
