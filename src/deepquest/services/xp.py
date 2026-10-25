"""Расчёт XP и журнал начислений.

Агент только выносит вердикт; сколько это в XP, решает формула здесь:

    XP = round(оценка_мин × value_mult × validation_mult × proof_mult × weak_mult)

Время по таймеру в XP не идёт (решено 2026-10-25): таймеров бывает несколько сразу, а
между делом отвлекаешься. Засчитывается оценка — задача заняла больше или меньше, её
правят вручную, и XP пересчитывается. До этого считалось min(таймер, 2 × оценка): в старых
начислениях counted_min — как было тогда.

weak_mult — ×1.2, если цель задачи сейчас самый слабый стат (services/character.py).
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import Task, User, ValidationVerdict, XpEvent, XpKind
from deepquest.services.days import season_of, user_logical_date

XP_PER_MINUTE = 1
VALIDATION_MULTS = {
    ValidationVerdict.ACCEPTED: 1.0,
    ValidationVerdict.PARTIAL: 0.7,
    ValidationVerdict.REJECTED: 0.0,
}
# Пруф — не доказательство, а данные для истории (решено 2026-10-21): без него ×1,
# со скрином или ссылкой — небольшой бонус.
NO_PROOF_MULT = 1.0
PROOF_MULT = 1.1
# За каждую запись в дневник: копим данные для будущих ретроспектив. Откалибруем позже.
DIARY_ENTRY_XP = 15


@dataclass(frozen=True)
class XpBreakdown:
    # По таймеру — для истории, на XP не влияет.
    actual_min: int
    estimate_min: int
    counted_min: int
    value_mult: float
    verdict: str
    validation_mult: float
    honor_mode: bool
    proof_mult: float
    amount: int
    # В начислениях до появления статов этого поля нет: там бонуса не было.
    weak_mult: float = 1.0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> XpBreakdown:
        return cls(**data)


def compute_task_xp(
    *,
    actual_min: int,
    estimate_min: int,
    value_mult: float,
    verdict: ValidationVerdict,
    honor_mode: bool,
    weak_mult: float = 1.0,
) -> XpBreakdown:
    counted = estimate_min
    validation_mult = VALIDATION_MULTS[verdict]
    proof_mult = NO_PROOF_MULT if honor_mode else PROOF_MULT
    amount = round(counted * XP_PER_MINUTE * value_mult * validation_mult * proof_mult * weak_mult)
    return XpBreakdown(
        actual_min=actual_min,
        estimate_min=estimate_min,
        counted_min=counted,
        value_mult=value_mult,
        verdict=verdict.value,
        validation_mult=validation_mult,
        honor_mode=honor_mode,
        proof_mult=proof_mult,
        amount=amount,
        weak_mult=weak_mult,
    )


async def task_xp(session: AsyncSession, task: Task) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(XpEvent.task_id == task.id)
    )
    return total or 0


async def total_xp(session: AsyncSession, user: User) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(XpEvent.user_id == user.id)
    )
    return total or 0


async def first_event(session: AsyncSession, task: Task) -> XpEvent | None:
    return await session.scalar(
        select(XpEvent).where(XpEvent.task_id == task.id).order_by(XpEvent.id).limit(1)
    )


async def latest_event(session: AsyncSession, task: Task) -> XpEvent | None:
    return await session.scalar(
        select(XpEvent).where(XpEvent.task_id == task.id).order_by(XpEvent.id.desc()).limit(1)
    )


async def record_task_xp(
    session: AsyncSession, user: User, task: Task, breakdown: XpBreakdown, now: datetime
) -> XpEvent:
    """Пишет начисление за задачу. Если по задаче уже что-то начислено (оспаривание),
    пишет поправку — разницу до нового итога, старые записи не трогает."""
    already = await task_xp(session, task)
    has_events = await latest_event(session, task) is not None
    day = user_logical_date(user, now)
    event = XpEvent(
        user_id=user.id,
        task_id=task.id,
        goal_id=task.goal_id,
        kind=XpKind.CORRECTION if has_events else XpKind.TASK,
        amount=breakdown.amount - already,
        breakdown=breakdown.to_json(),
        logical_date=day,
        season=season_of(day),
    )
    session.add(event)
    await session.flush()
    return event


async def season_xp(session: AsyncSession, user: User, season: str) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
            XpEvent.user_id == user.id, XpEvent.season == season
        )
    )
    return total or 0


async def record_diary_xp(
    session: AsyncSession, user: User, entry_id: int, day: date, amount: int = DIARY_ENTRY_XP
) -> XpEvent:
    """Начисление за запись в дневник (или минус при её удалении). В цель не идёт:
    дневник качает общий уровень, а не стат."""
    event = XpEvent(
        user_id=user.id,
        diary_entry_id=entry_id,
        kind=XpKind.DIARY,
        amount=amount,
        breakdown={"diary_entry_id": entry_id},
        logical_date=day,
        season=season_of(day),
    )
    session.add(event)
    await session.flush()
    return event


async def diary_entry_xp(session: AsyncSession, entry_id: int) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.amount), 0)).where(XpEvent.diary_entry_id == entry_id)
    )
    return total or 0


# Засчитанные минуты


@dataclass(frozen=True)
class Credit:
    """Сколько минут засчитано за закрытую задачу и в какой день."""

    task_id: int
    goal_id: int | None
    day: date
    minutes: int


async def credits(
    session: AsyncSession, user: User, first: date | None = None, last: date | None = None
) -> list[Credit]:
    """Засчитанные минуты закрытых задач — на них, а не на таймер, смотрят норма, стрик,
    графики и итоги (решено 2026-10-25). День — когда задачу закрыли (первое начисление),
    минуты — из последнего начисления: поправка оценки задним числом меняет их, но не день.
    Отклонённая задача — 0 минут."""
    query = select(XpEvent.task_id, XpEvent.goal_id, XpEvent.logical_date).where(
        XpEvent.user_id == user.id, XpEvent.kind == XpKind.TASK, XpEvent.task_id.is_not(None)
    )
    if first is not None:
        query = query.where(XpEvent.logical_date >= first)
    if last is not None:
        query = query.where(XpEvent.logical_date <= last)
    closed = list(await session.execute(query))
    if not closed:
        return []
    latest_ids = (
        select(func.max(XpEvent.id))
        .where(XpEvent.task_id.in_([task_id for task_id, _, _ in closed]))
        .group_by(XpEvent.task_id)
    )
    latest = dict(
        (task_id, breakdown)
        for task_id, breakdown in await session.execute(
            select(XpEvent.task_id, XpEvent.breakdown).where(XpEvent.id.in_(latest_ids))
        )
    )
    result = []
    for task_id, goal_id, day in closed:
        assert task_id is not None
        breakdown = latest.get(task_id) or {}
        rejected = breakdown.get("verdict") == ValidationVerdict.REJECTED.value
        minutes = 0 if rejected else int(breakdown.get("counted_min", 0))
        result.append(Credit(task_id, goal_id, day, minutes))
    return result
