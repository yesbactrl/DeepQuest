"""Сон: ночной и дневной, по отрезкам «лёг — встал».

Сон относится к дню пробуждения: ночь 23:30–07:00 — сон «на» тот день, когда встал. Так у дня
одна ночь (до неё) и сколько угодно дневного сна, а статистика легко ложится рядом с дневником
и фокусом того же дня. День — местная календарная дата пробуждения, без границы логического
дня: с ней ночь, закончившаяся в 03:30, ушла бы во «вчера».

Время веб передаёт и получает местным, в поясе пользователя, без смещения: так ввод и шкала
не зависят от пояса браузера.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import DiaryEntry, SleepKind, SleepSession, User
from deepquest.services.streak import focus_by_day

MIN_DURATION = timedelta(minutes=5)
MAX_DURATION = timedelta(hours=20)
MAX_NOTE_LEN = 300
MIN_GOAL_MIN, MAX_GOAL_MIN = 4 * 60, 12 * 60
# Недосып — меньше нормы больше чем на час.
SHORT_MARGIN_MIN = 60


class SleepError(ValueError):
    """Сон не сохранить: текст ошибки показывается пользователю как есть."""


def to_utc(user: User, local: datetime) -> datetime:
    return local.replace(tzinfo=ZoneInfo(user.tz)).astimezone(UTC)


def to_local(user: User, moment: datetime) -> datetime:
    return moment.astimezone(ZoneInfo(user.tz)).replace(tzinfo=None)


def _hhmm(user: User, moment: datetime) -> str:
    return f"{to_local(user, moment):%H:%M}"


async def _check(
    session: AsyncSession,
    user: User,
    start: datetime,
    end: datetime,
    now: datetime,
    skip_id: int | None = None,
) -> None:
    if end <= start:
        raise SleepError("Проснуться можно только после того, как лёг.")
    if end - start < MIN_DURATION:
        raise SleepError("Сон короче 5 минут не записывается.")
    if end - start > MAX_DURATION:
        raise SleepError("Больше 20 часов подряд — похоже на опечатку в дате.")
    if end > now + timedelta(minutes=5):
        raise SleepError("Этот сон ещё не закончился: записать можно после пробуждения.")
    query = select(SleepSession).where(
        SleepSession.user_id == user.id,
        SleepSession.started_at < end,
        SleepSession.ended_at > start,
    )
    if skip_id is not None:
        query = query.where(SleepSession.id != skip_id)
    other = await session.scalar(query.limit(1))
    if other is not None:
        raise SleepError(
            f"Пересекается с другим сном: {_hhmm(user, other.started_at)}–"
            f"{_hhmm(user, other.ended_at)}, {to_local(user, other.ended_at):%d.%m}."
        )


def _quality(value: int | None) -> int | None:
    return value if value is not None and 1 <= value <= 10 else None


def _note(text: str | None) -> str | None:
    return " ".join((text or "").split())[:MAX_NOTE_LEN] or None


@dataclass(frozen=True)
class SleepInput:
    kind: SleepKind
    # Местное время пользователя, без пояса.
    start: datetime
    end: datetime
    quality: int | None = None
    note: str | None = None


async def add_session(
    session: AsyncSession, user: User, data: SleepInput, now: datetime
) -> SleepSession:
    start, end = to_utc(user, data.start), to_utc(user, data.end)
    await _check(session, user, start, end, now)
    sleep = SleepSession(
        user_id=user.id,
        kind=data.kind,
        started_at=start,
        ended_at=end,
        day=data.end.date(),
        quality=_quality(data.quality),
        note=_note(data.note),
    )
    session.add(sleep)
    await session.flush()
    return sleep


async def edit_session(
    session: AsyncSession, user: User, sleep: SleepSession, data: SleepInput, now: datetime
) -> None:
    start, end = to_utc(user, data.start), to_utc(user, data.end)
    await _check(session, user, start, end, now, skip_id=sleep.id)
    sleep.kind = data.kind
    sleep.started_at, sleep.ended_at = start, end
    sleep.day = data.end.date()
    sleep.quality = _quality(data.quality)
    sleep.note = _note(data.note)
    await session.flush()


async def get_session(session: AsyncSession, user: User, sleep_id: int) -> SleepSession | None:
    return await session.scalar(
        select(SleepSession).where(SleepSession.id == sleep_id, SleepSession.user_id == user.id)
    )


def set_goal(user: User, minutes: int) -> None:
    if not MIN_GOAL_MIN <= minutes <= MAX_GOAL_MIN:
        raise SleepError("Норма сна — от 4 до 12 часов.")
    user.sleep_goal_min = minutes


def today(user: User, now: datetime) -> date:
    return to_local(user, now).date()


async def sessions_between(
    session: AsyncSession, user: User, first: date, last: date
) -> list[SleepSession]:
    return list(
        await session.scalars(
            select(SleepSession)
            .where(
                SleepSession.user_id == user.id,
                SleepSession.day >= first,
                SleepSession.day <= last,
            )
            .order_by(SleepSession.started_at)
        )
    )


def _minutes(sleep: SleepSession) -> int:
    return int((sleep.ended_at - sleep.started_at).total_seconds() // 60)


@dataclass(frozen=True)
class DaySleep:
    day: date
    sessions: list[SleepSession]
    night_min: int
    nap_min: int
    # Когда лёг и встал в главную (самую долгую) ночь дня — местное время.
    bedtime: datetime | None
    wake: datetime | None
    quality: float | None

    @property
    def total_min(self) -> int:
        return self.night_min + self.nap_min


def by_day(user: User, sessions: list[SleepSession]) -> dict[date, DaySleep]:
    grouped: dict[date, list[SleepSession]] = defaultdict(list)
    for sleep in sessions:
        grouped[sleep.day].append(sleep)
    result = {}
    for day, items in grouped.items():
        nights = [s for s in items if s.kind == SleepKind.NIGHT]
        main = max(nights, key=_minutes) if nights else None
        qualities = [s.quality for s in items if s.quality is not None]
        result[day] = DaySleep(
            day=day,
            sessions=items,
            night_min=sum(_minutes(s) for s in nights),
            nap_min=sum(_minutes(s) for s in items if s.kind == SleepKind.NAP),
            bedtime=to_local(user, main.started_at) if main else None,
            wake=to_local(user, main.ended_at) if main else None,
            quality=round(mean(qualities), 1) if qualities else None,
        )
    return result


def _since_noon(moment: datetime) -> int:
    """Минуты от полудня: 23:00 → 660, 01:00 → 780. Так среднее время отбоя не ломается
    о полночь: среднее 23:00 и 01:00 — полночь, а не полдень."""
    return (moment.hour * 60 + moment.minute - 12 * 60) % (24 * 60)


def _clock(minutes_since_noon: float) -> int:
    return int(round(minutes_since_noon + 12 * 60)) % (24 * 60)


@dataclass(frozen=True)
class SleepGroup:
    """Дни с недосыпом или со сном не меньше нормы: какое в них было состояние и фокус."""

    days: int
    state: float | None
    focus_min: float | None


@dataclass(frozen=True)
class SleepStats:
    days: int  # дней с записанным сном
    avg_total_min: int | None
    avg_night_min: int | None
    avg_nap_min: int | None
    # Среднее время отбоя и подъёма — минуты от полуночи.
    avg_bedtime: int | None
    avg_wake: int | None
    # Насколько гуляет время отбоя: стандартное отклонение в минутах.
    bedtime_spread_min: int | None
    goal_met: int
    # Сколько не доспал против нормы за дни с записями (переспанное не вычитается).
    debt_min: int
    avg_quality: float | None
    short: SleepGroup
    enough: SleepGroup


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _int(value: float | None) -> int | None:
    return None if value is None else int(round(value))


async def stats(
    session: AsyncSession,
    user: User,
    days: dict[date, DaySleep],
    first: date,
    last: date,
    now: datetime,
) -> SleepStats:
    items = list(days.values())
    goal = user.sleep_goal_min
    nights = [d for d in items if d.bedtime is not None and d.wake is not None]
    bedtimes = [_since_noon(d.bedtime) for d in nights if d.bedtime]
    qualities = [d.quality for d in items if d.quality is not None]

    # Состояние дня по дневнику и фокус — рядом с тем, сколько спал перед этим днём.
    states: dict[date, list[int]] = defaultdict(list)
    for entry in await session.scalars(
        select(DiaryEntry).where(
            DiaryEntry.user_id == user.id,
            DiaryEntry.logical_date >= first,
            DiaryEntry.logical_date <= last,
        )
    ):
        states[entry.logical_date] += [
            v for v in (entry.mood, entry.energy, entry.drive) if v is not None
        ]
    focus = await focus_by_day(session, user, first, last)

    def group(selected: list[DaySleep]) -> SleepGroup:
        return SleepGroup(
            days=len(selected),
            state=_avg([mean(states[d.day]) for d in selected if states.get(d.day)]),
            focus_min=_avg([focus.get(d.day, 0) for d in selected]),
        )

    return SleepStats(
        days=len(items),
        avg_total_min=_int(_avg([d.total_min for d in items])),
        avg_night_min=_int(_avg([d.night_min for d in items])),
        avg_nap_min=_int(_avg([d.nap_min for d in items])),
        avg_bedtime=_clock(mean(bedtimes)) if bedtimes else None,
        avg_wake=_int(_avg([d.wake.hour * 60 + d.wake.minute for d in nights if d.wake])),
        bedtime_spread_min=int(round(pstdev(bedtimes))) if len(bedtimes) > 1 else None,
        goal_met=sum(1 for d in items if d.total_min >= goal),
        debt_min=sum(max(goal - d.total_min, 0) for d in items),
        avg_quality=_avg(qualities),
        short=group([d for d in items if d.total_min < goal - SHORT_MARGIN_MIN]),
        enough=group([d for d in items if d.total_min >= goal]),
    )


@dataclass(frozen=True)
class SleepOverview:
    first: date
    last: date
    goal_min: int
    days: list[DaySleep]  # свежие сверху, только дни с записями
    stats: SleepStats


async def overview(session: AsyncSession, user: User, span: int, now: datetime) -> SleepOverview:
    last = today(user, now)
    first = last - timedelta(days=span - 1)
    days = by_day(user, await sessions_between(session, user, first, last))
    return SleepOverview(
        first=first,
        last=last,
        goal_min=user.sleep_goal_min,
        days=sorted(days.values(), key=lambda d: d.day, reverse=True),
        stats=await stats(session, user, days, first, last, now),
    )
