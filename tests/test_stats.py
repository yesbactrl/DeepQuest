from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.db.models import (
    DayStats,
    DayStatus,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    XpEvent,
    XpKind,
)
from deepquest.services import goals, streak
from deepquest.services.charts import Bucket, ChartConfig, Metric, Period, Split, chart_data
from deepquest.services.days import season_of, split_by_day
from deepquest.services.levels import level_of, xp_to_next
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields, create_draft
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import BotHarness, FakeAgent

ME = 111
# Четверг 22 октября, полдень по UTC. Неделя 43 — с понедельника 19 октября.
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


# Уровни и границы дня


def test_level_steps_grow() -> None:
    assert [xp_to_next(level) for level in range(1, 6)] == [100, 264, 466, 696, 952]


@pytest.mark.parametrize(
    ("xp", "level", "floor", "next_"),
    [
        (0, 1, 0, 100),
        (99, 1, 0, 100),
        (100, 2, 100, 364),
        (1526, 5, 1526, 2478),
        (9237, 10, 9237, 11749),
        (-5, 1, 0, 100),
    ],
)
def test_level_of(xp: int, level: int, floor: int, next_: int) -> None:
    result = level_of(xp)
    assert (result.level, result.floor_xp, result.next_xp) == (level, floor, next_)


def test_level_progress() -> None:
    assert level_of(232).progress == pytest.approx(0.5)


def test_split_by_day_respects_boundary() -> None:
    user = User(tz="Europe/Moscow", day_boundary_hour=4)
    # 03:30–04:30 по Москве: полчаса во «вчера», полчаса в «сегодня».
    pieces = split_by_day(user, at(21, 0, 30), at(21, 1, 30))
    assert pieces == [(date(2026, 10, 20), 1800.0), (date(2026, 10, 21), 1800.0)]


# Закрытие дней и стрик


@dataclass
class Seed:
    user_id: int
    income: int
    arbitrage: int
    health: int


async def _entry(
    session: AsyncSession, user: User, task: Task, start: datetime, end: datetime | None
) -> None:
    session.add(TimeEntry(user_id=user.id, task_id=task.id, started_at=start, ended_at=end))


@pytest.fixture
async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> Seed:
    """Норма 60 мин, одна заморозка в неделю, живём по UTC с границей дня в 04:00."""
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz, user.daily_norm_min, user.freezes_per_week = "UTC", 60, 1
        user.created_at = at(17, 10)
        income = await goals.create_goal(session, user, "Свой доход", "Свобода")
        arbitrage = await goals.create_goal(session, user, "Арбитраж", None, income)
        health = await goals.create_goal(session, user, "Здоровье", "Энергия")
        work = await create_draft(
            session, user, TaskFields("Кампания", None, arbitrage.id, 60, 1.0, None), "т", None
        )
        gym = await create_draft(
            session, user, TaskFields("Зал", None, health.id, 60, 1.0, None), "т", None
        )
        await _entry(session, user, work, at(17, 10), at(17, 11, 30))  # 17-е: 90 мин
        await _entry(session, user, gym, at(21, 3, 30), at(21, 4, 30))  # 20-е: 30, 21-е: 30
        await _entry(session, user, gym, at(21, 9), at(21, 10, 10))  # 21-е: ещё 70
        await _entry(session, user, work, at(22, 11, 30), None)  # сегодня: таймер идёт 30 мин
        await session.commit()
        return Seed(user.id, income.id, arbitrage.id, health.id)


async def _user(session: AsyncSession, seed: Seed) -> User:
    user = await session.get(User, seed.user_id)
    assert user is not None
    return user


async def test_close_days_with_weekly_freezes(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        info = await streak.streak_info(session, await _user(session, seed), NOW)
        await session.commit()
        rows = list(await session.scalars(select(DayStats).order_by(DayStats.logical_date)))

    assert [(r.logical_date.day, r.focus_min, r.status) for r in rows] == [
        (17, 90, DayStatus.MET),
        (18, 0, DayStatus.FROZEN),  # неделя 42: заморозка
        (19, 0, DayStatus.FROZEN),  # неделя 43: своя заморозка
        (20, 30, DayStatus.MISSED),  # заморозки недели кончились
        (21, 100, DayStatus.MET),
    ]
    assert (info.current, info.best) == (1, 3)
    assert (info.today_focus_min, info.today_met) == (30, False)
    assert (info.freezes_left, info.freezes_per_week) == (0, 1)
    assert [m.status for m in info.recent] == ["met", "frozen", "frozen", "missed", "met", "today"]


async def test_close_days_is_idempotent_and_keeps_norm_snapshot(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        await streak.close_days(session, user, NOW)
        user.daily_norm_min = 120
        await streak.close_days(session, user, NOW)
        await streak.close_days(session, user, NOW + timedelta(days=1))
        await session.commit()
        rows = list(await session.scalars(select(DayStats).order_by(DayStats.logical_date)))

    assert len(rows) == 6  # 17–21 и закрывшееся 22-е
    assert rows[0].norm_min == 60  # старые дни не пересчитались под новую норму
    assert (rows[-1].logical_date, rows[-1].norm_min) == (date(2026, 10, 22), 120)


async def test_today_counts_once_norm_is_met(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        # Таймер сегодня идёт уже час: норма выполнена, стрик +1.
        info = await streak.streak_info(
            session, await _user(session, seed), NOW + timedelta(minutes=30)
        )
    assert (info.today_focus_min, info.today_met, info.current) == (60, True, 2)


# Графики


async def _xp(
    session: AsyncSession,
    user: User,
    goal_id: int,
    day: date,
    amount: int,
    task: Task | None = None,
    kind: XpKind = XpKind.TASK,
) -> None:
    session.add(
        XpEvent(
            user_id=user.id,
            task_id=task.id if task else None,
            goal_id=goal_id,
            kind=kind,
            amount=amount,
            breakdown={},
            logical_date=day,
            season=season_of(day),
        )
    )


async def test_minutes_by_day_and_goal(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        data = await chart_data(
            session, user, ChartConfig(metric=Metric.MINUTES, period=Period.WEEK), NOW
        )

    assert data.buckets[0] == "2026-10-16" and data.buckets[-1] == "2026-10-22"
    assert data.labels[-1] == "22.10"
    by_name = {s.name: s.values for s in data.series}
    # Направление «Арбитраж» складывается в цель «Свой доход».
    assert by_name["Свой доход"] == [0, 90, 0, 0, 0, 0, 30]
    assert by_name["Здоровье"] == [0, 0, 0, 0, 30, 100, 0]
    # «Здоровье» впереди по минутам, но цвет у целей по их порядку, а не по рейтингу.
    assert [(s.name, s.slot) for s in data.series] == [("Здоровье", 1), ("Свой доход", 0)]
    assert data.norm_min == 60


async def test_goal_filter_splits_by_direction_and_weeks(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        direct = await create_draft(
            session, user, TaskFields("Напрямую", None, seed.income, 60, 1.0, None), "т", None
        )
        await _entry(session, user, direct, at(20, 10), at(20, 10, 45))
        config = ChartConfig(
            metric=Metric.MINUTES, bucket=Bucket.WEEK, period=Period.MONTH, goal_id=seed.income
        )
        data = await chart_data(session, user, config, NOW)

    assert data.labels[-2:] == ["с 12.10", "с 19.10"]
    by_name = {s.name: s.values[-2:] for s in data.series}
    assert by_name == {"Арбитраж": [90, 30], "Свой доход (без направления)": [0, 45]}
    assert data.norm_min is None


async def test_xp_and_closed_tasks(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        done = await create_draft(
            session, user, TaskFields("Готово", None, seed.arbitrage, 60, 1.0, None), "т", None
        )
        rejected = await create_draft(
            session, user, TaskFields("Отклонено", None, seed.health, 60, 1.0, None), "т", None
        )
        done.status, rejected.status = TaskStatus.DONE, TaskStatus.REJECTED
        await _xp(session, user, seed.arbitrage, date(2026, 10, 20), 120, done)
        await _xp(session, user, seed.arbitrage, date(2026, 10, 21), -20, done, XpKind.CORRECTION)
        await _xp(session, user, seed.health, date(2026, 10, 21), 0, rejected)

        xp_total = await chart_data(
            session,
            user,
            ChartConfig(metric=Metric.XP, split=Split.NONE, period=Period.SEASON),
            NOW,
        )
        tasks_by_goal = await chart_data(
            session, user, ChartConfig(metric=Metric.TASKS, period=Period.WEEK), NOW
        )

    [total] = xp_total.series
    assert (total.name, total.total, len(xp_total.buckets)) == ("XP", 100, 22)
    assert [(s.name, s.total) for s in tasks_by_goal.series] == [("Свой доход", 1)]


# API и бот


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(sessionmaker, ME, tmp_path / "dist", FakeAgent(), ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


async def test_summary_api(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        # API берёт реальное «сейчас»: начисление кладём в текущий сезон.
        await _xp(session, user, seed.health, datetime.now(UTC).date(), 700)
        await session.commit()

    summary = (await client.get("/api/summary")).json()

    assert (summary["total"]["level"], summary["total"]["xp"]) == (3, 700)
    assert summary["season_level"]["level"] == 3
    assert summary["streak"]["norm_min"] == 60
    assert summary["streak"]["recent"][-1]["status"] == "today"


async def test_series_api_validates_config(client: httpx.AsyncClient, seed: Seed) -> None:
    ok = await client.get(
        "/api/stats/series", params={"metric": "xp", "bucket": "month", "period": "365d"}
    )
    assert ok.status_code == 200
    assert ok.json()["labels"][-1] == "окт 2026"
    bad = await client.get("/api/stats/series", params={"metric": "money"})
    assert bad.status_code == 422


async def test_dashboard_defaults_then_user_owns_it(client: httpx.AsyncClient, seed: Seed) -> None:
    widgets = (await client.get("/api/dashboard")).json()
    assert [w["config"]["title"] for w in widgets] == [
        "Фокус по дням",
        "Время по целям",
        "XP по неделям",
    ]

    one = {"title": "Только XP", "metric": "xp", "chart": "line", "size": "full"}
    saved = (await client.put("/api/dashboard", json=[one])).json()
    assert [(w["position"], w["config"]["title"], w["config"]["bucket"]) for w in saved] == [
        (0, "Только XP", "day")
    ]

    assert (await client.put("/api/dashboard", json=[])).json() == []
    # Удалил всё — графики по умолчанию сами не возвращаются.
    assert (await client.get("/api/dashboard")).json() == []

    too_many = await client.put("/api/dashboard", json=[one] * 13)
    assert too_many.status_code == 422
    wrong = await client.put("/api/dashboard", json=[{"chart": "radar"}])
    assert wrong.status_code == 422


async def test_bot_stats(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/stats")

    text = harness.last_text
    assert "Уровень <b>1</b>" in text
    assert "Сезон «" in text
    assert "Стрик:" in text and "🟩" in text
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(DayStats)) > 0
