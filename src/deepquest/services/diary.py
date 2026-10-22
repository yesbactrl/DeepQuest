"""Дневник состояния: короткие записи, которые агент раскладывает на настроение, энергию,
желание действовать, эмоции и факторы. Числа предлагает агент, последнее слово — за
пользователем: поправленные вручную оценки повторный разбор не трогает.

Как и при оформлении задач, перед вызовом модели транзакция фиксируется: SQLite не должен
держать блокировку записи, пока ждём ответ.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.base import AgentError, TaskAgent
from deepquest.agent.schemas import DiaryAnalysis, DiaryContext, DiarySphereNote, GoalContext
from deepquest.db.models import DiaryEntry, DiarySphere, DiaryStatus, User, XpEvent
from deepquest.services import xp
from deepquest.services.agent_log import record_calls
from deepquest.services.days import local_time, user_logical_date
from deepquest.services.planning import goal_context
from deepquest.services.streak import focus_by_day

logger = logging.getLogger(__name__)

MAX_TEXT_LEN = 4000
MAX_TAGS = 6
MAX_TAG_LEN = 40
MAX_SUMMARY_LEN = 120
MAX_NOTE_LEN = 160
# Сколько прошлых факторов и эмоций подсказывать агенту, чтобы он брал те же слова.
KNOWN_TAGS = 40

PARTS_OF_DAY = {"morning": "утро", "day": "день", "evening": "вечер"}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip


class DiaryError(ValueError):
    """Действие с записью невозможно: скажем, разбирать нечего."""


def part_of_day(user: User, moment: datetime) -> str:
    """Утро — от границы дня до полудня, день — до 18:00, вечер — до следующей границы."""
    hour = local_time(user, moment).hour
    if user.day_boundary_hour <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "day"
    return "evening"


def _written_at(user: User, entry: DiaryEntry) -> str:
    moment = local_time(user, entry.created_at)
    return (
        f"{WEEKDAYS[moment.weekday()]}, {moment.day} {MONTHS[moment.month - 1]}, "
        f"{moment:%H:%M} ({PARTS_OF_DAY[entry.part_of_day]})"
    )


def clean_tags(tags: list[str]) -> list[str]:
    """Теги со строчной буквы, без повторов и пустых, не больше MAX_TAGS."""
    result: list[str] = []
    for tag in tags:
        tag = " ".join(tag.split()).lower()[:MAX_TAG_LEN]
        if tag and tag not in result:
            result.append(tag)
    return result[:MAX_TAGS]


# Сферы оцениваются подробнее, чем общее состояние: 1–10 против 1–5.
SPHERE_MAX = 10


def _sphere_score(value: int | None) -> int | None:
    return value if value is not None and 1 <= value <= SPHERE_MAX else None


def _score(value: int | None) -> int | None:
    return value if value is not None and 1 <= value <= 5 else None


async def _known_tags(session: AsyncSession, user: User) -> tuple[tuple[str, ...], tuple[str, ...]]:
    rows = await session.execute(
        select(DiaryEntry.factors, DiaryEntry.emotions).where(DiaryEntry.user_id == user.id)
    )
    factors: Counter[str] = Counter()
    emotions: Counter[str] = Counter()
    for entry_factors, entry_emotions in rows:
        factors.update(entry_factors or [])
        emotions.update(entry_emotions or [])
    return (
        tuple(tag for tag, _ in factors.most_common(KNOWN_TAGS)),
        tuple(tag for tag, _ in emotions.most_common(KNOWN_TAGS)),
    )


def _note(text: str | None) -> str | None:
    return " ".join((text or "").split())[:MAX_NOTE_LEN] or None


@dataclass(frozen=True)
class SphereEdit:
    goal_id: int
    score: int | None = None
    good: str | None = None
    bad: str | None = None


def _roots(goals: list[GoalContext]) -> dict[int, int]:
    """id цели или её направления → id цели: сфера — всегда цель верхнего уровня."""
    roots: dict[int, int] = {}
    for goal in goals:
        roots[goal.id] = goal.id
        for direction in goal.directions:
            roots[direction.id] = goal.id
    return roots


def _set_spheres(
    entry: DiaryEntry, notes: list[SphereEdit], roots: dict[int, int], chosen: list[int]
) -> None:
    """Сферы записи: только активные цели, одна заметка на цель. Цели, которые
    пользователь отметил сам, остаются даже без заметки."""
    # Существующие строки переиспользуем: удаление и вставка той же пары (запись, цель)
    # в одном flush упёрлись бы в уникальный индекс.
    existing = {sphere.goal_id: sphere for sphere in entry.spheres}
    by_goal: dict[int, DiarySphere] = {}

    def put(goal_id: int, score: int | None, good: str | None, bad: str | None) -> None:
        sphere = existing.get(goal_id) or DiarySphere(goal_id=goal_id)
        sphere.score, sphere.good, sphere.bad = _sphere_score(score), _note(good), _note(bad)
        by_goal[goal_id] = sphere

    for note in notes:
        goal_id = roots.get(note.goal_id)
        if goal_id is not None and goal_id not in by_goal:
            put(goal_id, note.score, note.good, note.bad)
    for goal_id in chosen:
        root = roots.get(goal_id)
        if root is not None and root not in by_goal:
            put(root, None, None, None)
    entry.spheres = list(by_goal.values())


def _from_agent(notes: list[DiarySphereNote]) -> list[SphereEdit]:
    return [SphereEdit(n.goal_id, n.score, n.good, n.bad) for n in notes]


def _apply(
    entry: DiaryEntry, analysis: DiaryAnalysis, roots: dict[int, int], chosen: list[int]
) -> None:
    if not entry.edited:
        entry.mood = _score(analysis.mood)
        entry.energy = _score(analysis.energy)
        entry.drive = _score(analysis.drive)
        entry.emotions = clean_tags(analysis.emotions)
        entry.factors = clean_tags(analysis.factors)
        _set_spheres(entry, _from_agent(analysis.spheres), roots, chosen)
    entry.summary = " ".join(analysis.summary.split())[:MAX_SUMMARY_LEN] or None
    entry.status = DiaryStatus.DONE


async def _analyze(session: AsyncSession, agent: TaskAgent, user: User, entry: DiaryEntry) -> bool:
    """Разбор агентом. False — агент недоступен, запись остаётся «не разобрана».
    Сферы, уже отмеченные у записи, агент обязан разобрать."""
    factors, emotions = await _known_tags(session, user)
    goals = await goal_context(session, user)
    chosen = [sphere.goal_id for sphere in entry.spheres]
    context = DiaryContext(
        text=entry.text,
        written_at=_written_at(user, entry),
        known_factors=factors,
        known_emotions=emotions,
        goals=tuple(goals),
        chosen_goal_ids=tuple(chosen),
    )
    await session.commit()
    try:
        result = await agent.analyze_diary(context)
    except AgentError as exc:
        logger.warning("analyze_diary failed: %s", exc)
        await record_calls(session, user, exc.calls)
        entry.status = DiaryStatus.FAILED
        return False
    entry.agent_call_id = await record_calls(session, user, result.calls)
    _apply(entry, result.output, _roots(goals), chosen)
    return True


@dataclass
class EntryOutcome:
    entry: DiaryEntry
    agent_failed: bool = False
    # Сколько XP принесла запись (начисляется сразу, даже если агент недоступен).
    xp: int = 0


async def add_entry(
    session: AsyncSession,
    agent: TaskAgent,
    user: User,
    text: str,
    now: datetime,
    *,
    analyze: bool = True,
    goal_ids: list[int] | None = None,
) -> EntryOutcome:
    """Новая запись. `analyze=False` — не отдавать текст агенту: оценки тогда ставятся вручную.
    `goal_ids` — сферы, которые пользователь отметил сам: про них агент напишет обязательно."""
    text = text.strip()[:MAX_TEXT_LEN]
    if not text:
        raise DiaryError("Empty diary entry")
    entry = DiaryEntry(
        user_id=user.id,
        text=text,
        logical_date=user_logical_date(user, now),
        part_of_day=part_of_day(user, now),
        created_at=now,
        emotions=[],
        factors=[],
        status=DiaryStatus.FAILED if analyze else DiaryStatus.PRIVATE,
        spheres=[],
    )
    if goal_ids:
        _set_spheres(entry, [], _roots(await goal_context(session, user)), goal_ids)
    session.add(entry)
    await session.flush()
    award = await xp.record_diary_xp(session, user, entry.id, entry.logical_date)
    if not analyze:
        return EntryOutcome(entry, xp=award.amount)
    ok = await _analyze(session, agent, user, entry)
    return EntryOutcome(entry, agent_failed=not ok, xp=award.amount)


async def reanalyze(
    session: AsyncSession, agent: TaskAgent, user: User, entry: DiaryEntry
) -> EntryOutcome:
    """Разобрать ещё раз: после сбоя агента или если запись была «только для себя»."""
    ok = await _analyze(session, agent, user, entry)
    return EntryOutcome(entry, agent_failed=not ok)


async def get_entry(session: AsyncSession, user: User, entry_id: int) -> DiaryEntry | None:
    return await session.scalar(
        select(DiaryEntry).where(DiaryEntry.id == entry_id, DiaryEntry.user_id == user.id)
    )


@dataclass(frozen=True)
class EntryEdit:
    """Ручная правка. None — поле не меняется; у шкал 0 — «не знаю», убрать оценку."""

    text: str | None = None
    mood: int | None = None
    energy: int | None = None
    drive: int | None = None
    emotions: list[str] | None = None
    factors: list[str] | None = None
    summary: str | None = None
    # Сферы целиком: что прислали, то и остаётся.
    spheres: list[SphereEdit] | None = None


async def edit_entry(session: AsyncSession, user: User, entry: DiaryEntry, edit: EntryEdit) -> None:
    if edit.text is not None and edit.text.strip():
        entry.text = edit.text.strip()[:MAX_TEXT_LEN]
    for name in ("mood", "energy", "drive"):
        value = getattr(edit, name)
        if value is not None:
            setattr(entry, name, _score(value))
            entry.edited = True
    if edit.emotions is not None:
        entry.emotions = clean_tags(edit.emotions)
        entry.edited = True
    if edit.factors is not None:
        entry.factors = clean_tags(edit.factors)
        entry.edited = True
    if edit.summary is not None:
        entry.summary = " ".join(edit.summary.split())[:MAX_SUMMARY_LEN] or None
    if edit.spheres is not None:
        roots = _roots(await goal_context(session, user))
        _set_spheres(entry, edit.spheres, roots, [])
        entry.edited = True


async def delete_entry(session: AsyncSession, user: User, entry: DiaryEntry, now: datetime) -> None:
    """Удалить запись. Журнал XP только дописывается: начисленное за неё снимается минусом."""
    earned = await xp.diary_entry_xp(session, entry.id)
    if earned:
        await xp.record_diary_xp(
            session, user, entry.id, user_logical_date(user, now), amount=-earned
        )
    await session.execute(delete(DiaryEntry).where(DiaryEntry.id == entry.id))


@dataclass(frozen=True)
class Day:
    """День дневника: записи и средние оценки рядом с тем, сколько было работы."""

    day: date
    entries: list[DiaryEntry]
    mood: float | None
    energy: float | None
    drive: float | None
    focus_min: int
    xp: int


def _average(values: list[int | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(mean(present), 1) if present else None


async def list_days(
    session: AsyncSession, user: User, now: datetime, days: int, goal_id: int | None = None
) -> list[Day]:
    """Дни с записями за последние `days` дней, свежие сверху. `goal_id` — только записи
    про эту сферу."""
    today = user_logical_date(user, now)
    first = today - timedelta(days=days - 1)
    query = (
        select(DiaryEntry)
        .where(DiaryEntry.user_id == user.id, DiaryEntry.logical_date >= first)
        .order_by(DiaryEntry.created_at.desc(), DiaryEntry.id.desc())
    )
    if goal_id is not None:
        query = query.where(DiaryEntry.spheres.any(DiarySphere.goal_id == goal_id))
    entries = list(await session.scalars(query))
    by_day: dict[date, list[DiaryEntry]] = {}
    for entry in entries:
        by_day.setdefault(entry.logical_date, []).append(entry)
    if not by_day:
        return []
    focus = await focus_by_day(session, user, min(by_day), max(by_day), now)
    xp_rows = await session.execute(
        select(XpEvent.logical_date, func.sum(XpEvent.amount))
        .where(XpEvent.user_id == user.id, XpEvent.logical_date.in_(list(by_day)))
        .group_by(XpEvent.logical_date)
    )
    xp_by_day = {day: amount or 0 for day, amount in xp_rows}
    return [
        Day(
            day=day,
            entries=day_entries,
            mood=_average([e.mood for e in day_entries]),
            energy=_average([e.energy for e in day_entries]),
            drive=_average([e.drive for e in day_entries]),
            focus_min=focus.get(day, 0),
            xp=xp_by_day.get(day, 0),
        )
        for day, day_entries in sorted(by_day.items(), reverse=True)
    ]
