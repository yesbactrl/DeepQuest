"""Норма, закрытие дней и стрик.

- Минуты фокуса за день — засчитанные минуты задач, закрытых в этот логический день
  (`xp.credits`: оценка, поправленная пользователем, если задача заняла больше или
  меньше). Таймер на норму не влияет (решено 2026-10-25): таймеров бывает несколько сразу,
  а между делом отвлекаешься. Отклонённая задача в норму не идёт.
- Закрытие дня пишет `day_stats` со снимком нормы. Закрываются все незакрытые дни
  до вчерашнего включительно: Mac мог спать неделю, а вызывать можно сколько угодно раз.
- Заморозка спасает невыполненный день, если до него стрик был жив и на этой неделе
  (пн–вс по логическим дням) заморозки ещё остались.
- Стрик — подряд идущие дни met/frozen до вчера, плюс сегодня, если норма уже выполнена.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import DayStats, DayStatus, User
from deepquest.services import xp
from deepquest.services.days import user_logical_date

RECENT_DAYS = 14
_INSERT_CHUNK = 500


def _week(day: date) -> tuple[int, int]:
    iso = day.isocalendar()
    return iso.year, iso.week


def _days(first: date, last: date) -> Iterable[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


async def focus_by_day(
    session: AsyncSession, user: User, first: date, last: date
) -> dict[date, int]:
    """Засчитанные минуты по логическим дням за [first, last]."""
    minutes: dict[date, int] = defaultdict(int)
    for credit in await xp.credits(session, user, first, last):
        minutes[credit.day] += credit.minutes
    return dict(minutes)


async def close_days(session: AsyncSession, user: User, now: datetime) -> None:
    """Закрывает все незакрытые логические дни до вчерашнего включительно.
    Пока норма и стрик на паузе, дни не закрываются: их закроет `resume`."""
    if user.streak_paused_at is not None:
        return
    yesterday = user_logical_date(user, now) - timedelta(days=1)
    last = await session.scalar(
        select(DayStats)
        .where(DayStats.user_id == user.id)
        .order_by(DayStats.logical_date.desc())
        .limit(1)
    )
    # Жив ли стрик, решает последний день до паузы: дни на паузе не в счёт.
    last_counted = await session.scalar(
        select(DayStats.status)
        .where(DayStats.user_id == user.id, DayStats.status != DayStatus.PAUSED)
        .order_by(DayStats.logical_date.desc())
        .limit(1)
    )
    first = (
        last.logical_date + timedelta(days=1) if last else user_logical_date(user, user.created_at)
    )
    if first > yesterday:
        return

    focus = await focus_by_day(session, user, first, yesterday)
    # Заморозки, уже потраченные на неделе первого закрываемого дня.
    week_start = first - timedelta(days=first.weekday())
    frozen: dict[tuple[int, int], int] = defaultdict(int)
    already = await session.scalars(
        select(DayStats.logical_date).where(
            DayStats.user_id == user.id,
            DayStats.status == DayStatus.FROZEN,
            DayStats.logical_date >= week_start,
        )
    )
    for day in already:
        frozen[_week(day)] += 1

    alive = last_counted is not None and last_counted != DayStatus.MISSED
    rows = []
    for day in _days(first, yesterday):
        minutes = focus.get(day, 0)
        if minutes >= user.daily_norm_min:
            status = DayStatus.MET
        elif alive and frozen[_week(day)] < user.freezes_per_week:
            status = DayStatus.FROZEN
            frozen[_week(day)] += 1
        else:
            status = DayStatus.MISSED
        alive = status != DayStatus.MISSED
        rows.append(
            {
                "user_id": user.id,
                "logical_date": day,
                "focus_min": minutes,
                "norm_min": user.daily_norm_min,
                "status": status,
                "closed_at": now,
            }
        )
    # Бот и веб могут закрывать дни одновременно: уже закрытый день просто пропускаем.
    for i in range(0, len(rows), _INSERT_CHUNK):
        await session.execute(
            insert(DayStats)
            .values(rows[i : i + _INSERT_CHUNK])
            .on_conflict_do_nothing(index_elements=["user_id", "logical_date"])
        )


async def pause(session: AsyncSession, user: User, now: datetime) -> None:
    """Поставить норму и стрик на паузу. Дни до сегодняшнего сначала закрываются как обычно."""
    if user.streak_paused_at is not None:
        return
    await close_days(session, user, now)
    user.streak_paused_at = now


async def resume(session: AsyncSession, user: User, now: datetime) -> None:
    """Снять с паузы. Дни паузы до вчерашнего включительно записываются как `paused`:
    стрик сквозь них не рвётся и не растёт — продолжается с того места, где остановился."""
    if user.streak_paused_at is None:
        return
    first = user_logical_date(user, user.streak_paused_at)
    yesterday = user_logical_date(user, now) - timedelta(days=1)
    if first <= yesterday:
        focus = await focus_by_day(session, user, first, yesterday)
        rows = [
            {
                "user_id": user.id,
                "logical_date": day,
                "focus_min": focus.get(day, 0),
                "norm_min": user.daily_norm_min,
                "status": DayStatus.PAUSED,
                "closed_at": now,
            }
            for day in _days(first, yesterday)
        ]
        for i in range(0, len(rows), _INSERT_CHUNK):
            await session.execute(
                insert(DayStats)
                .values(rows[i : i + _INSERT_CHUNK])
                .on_conflict_do_nothing(index_elements=["user_id", "logical_date"])
            )
    user.streak_paused_at = None


@dataclass(frozen=True)
class DayMark:
    day: date
    # met / missed / frozen / paused для закрытых дней, today — для текущего.
    status: str
    focus_min: int
    norm_min: int


@dataclass(frozen=True)
class StreakInfo:
    current: int
    best: int
    today: date
    today_focus_min: int
    norm_min: int
    freezes_left: int
    freezes_per_week: int
    recent: list[DayMark]
    # Норма и стрик на паузе: интерфейс их прячет, стрик заморожен.
    paused: bool = False

    @property
    def today_met(self) -> bool:
        return self.today_focus_min >= self.norm_min


async def streak_info(session: AsyncSession, user: User, now: datetime) -> StreakInfo:
    await close_days(session, user, now)
    today = user_logical_date(user, now)
    rows = list(
        await session.scalars(
            select(DayStats).where(DayStats.user_id == user.id).order_by(DayStats.logical_date)
        )
    )
    today_focus = (await focus_by_day(session, user, today, today)).get(today, 0)
    today_met = today_focus >= user.daily_norm_min

    best = run = 0
    for row in rows:
        if row.status == DayStatus.PAUSED:
            continue
        run = 0 if row.status == DayStatus.MISSED else run + 1
        best = max(best, run)
    paused = user.streak_paused_at is not None
    # На паузе сегодняшний день в стрик не идёт: стрик заморожен на том, что было.
    current = run + (1 if today_met and not paused else 0)
    best = max(best, current)

    week = _week(today)
    used = sum(
        1 for row in rows if row.status == DayStatus.FROZEN and _week(row.logical_date) == week
    )
    recent = [
        DayMark(row.logical_date, row.status.value, row.focus_min, row.norm_min)
        for row in rows[-(RECENT_DAYS - 1) :]
    ]
    recent.append(DayMark(today, "today", today_focus, user.daily_norm_min))
    return StreakInfo(
        current=current,
        best=best,
        today=today,
        today_focus_min=today_focus,
        norm_min=user.daily_norm_min,
        freezes_left=max(user.freezes_per_week - used, 0),
        freezes_per_week=user.freezes_per_week,
        recent=recent,
        paused=paused,
    )
