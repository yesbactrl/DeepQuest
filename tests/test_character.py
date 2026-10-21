import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import get_args

import httpx
import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.base import render_goals
from deepquest.bot import texts
from deepquest.db.migrate import alembic_config
from deepquest.db.models import Goal, TimeEntry, User, XpEvent, XpKind
from deepquest.services import goals, planning, tasks
from deepquest.services.character import _weakest, build_character
from deepquest.services.charts import ChartConfig, Metric, Period, Split, chart_data
from deepquest.services.days import season_of
from deepquest.services.goals import PALETTE
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.services.xp import XpBreakdown
from deepquest.web.app import create_app
from deepquest.web.schemas import GoalColor
from tests.conftest import BotHarness, FakeAgent, verdict

ME = 111


@dataclass
class Seed:
    user_id: int
    capital: int
    arbitrage: int
    health: int
    sport: int


async def _xp(
    session: AsyncSession, user: User, goal_id: int | None, amount: int, **kw: object
) -> None:
    day = kw.pop("day", datetime.now(UTC).date())
    assert isinstance(day, date)
    session.add(
        XpEvent(
            user_id=user.id,
            goal_id=goal_id,
            kind=kw.pop("kind", XpKind.TASK),
            amount=amount,
            breakdown={},
            logical_date=day,
            season=season_of(day),
            task_id=kw.pop("task_id", None),
        )
    )
    await session.flush()


@pytest.fixture
async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> Seed:
    """Капитал (направление Арбитраж) и Здоровье (направление Спорт), онбординг пройден."""
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz, user.onboarded_at = "UTC", datetime.now(UTC)
        capital = await goals.create_goal(session, user, "Капитал", "Подушка и свобода")
        arbitrage = await goals.create_goal(session, user, "Арбитраж", None, capital)
        health = await goals.create_goal(session, user, "Здоровье", "Энергия")
        sport = await goals.create_goal(session, user, "Спорт", None, health)
        await session.commit()
        return Seed(user.id, capital.id, arbitrage.id, health.id, sport.id)


async def _user(session: AsyncSession, seed: Seed) -> User:
    user = await session.get(User, seed.user_id)
    assert user is not None
    return user


# Самый слабый стат


@pytest.mark.parametrize(
    ("season_xp", "weakest"),
    [
        ({1: 0}, set()),  # один стат сравнивать не с чем
        ({1: 0, 2: 0, 3: 0}, set()),  # все наравне — отстающего нет
        ({1: 100, 2: 0, 3: 40}, {2}),
        ({1: 100, 2: 0, 3: 0}, {2, 3}),
    ],
)
def test_weakest_stat(season_xp: dict[int, int], weakest: set[int]) -> None:
    assert _weakest(season_xp) == weakest


def test_old_breakdowns_have_no_weak_bonus() -> None:
    old = {
        "actual_min": 60,
        "estimate_min": 60,
        "counted_min": 60,
        "value_mult": 1.0,
        "verdict": "accepted",
        "validation_mult": 1.0,
        "honor_mode": False,
        "proof_mult": 1.0,
        "amount": 60,
    }
    assert XpBreakdown.from_json(old).weak_mult == 1.0


async def _report(
    sessionmaker: async_sessionmaker[AsyncSession], harness: BotHarness, seed: Seed, goal_id: int
) -> None:
    """Задача на 60 минут по цели `goal_id`: старт, час работы, «Готово» и отчёт со ссылкой."""
    async with sessionmaker() as session:
        user = await _user(session, seed)
        fields = TaskFields("Сходить в зал", "Тренировка", goal_id, 60, 1.0, "обычная работа")
        task = await tasks.create_draft(session, user, fields, "зал", None)
        tasks.save_task(task)
        await session.commit()
    await harness.send(ME, "/backlog")
    await harness.tap(ME, "1")
    await harness.tap(ME, texts.START_BUTTON)
    async with sessionmaker() as session:
        for entry in await session.scalars(select(TimeEntry)):
            entry.started_at -= timedelta(minutes=60)
        await session.commit()
    await harness.tap(ME, texts.DONE_BUTTON)
    await harness.send(ME, "Отзанимался: https://example.com/workout")


async def test_weakest_stat_gets_bonus_and_keeps_it_on_dispute(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        await _xp(session, await _user(session, seed), seed.arbitrage, 100)
        await session.commit()
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations += [verdict("accepted"), verdict("partial")]

    await _report(sessionmaker, harness, seed, seed.sport)

    # 60 мин × 1 × 1 × 1 × 1.2: Здоровье отстаёт от Капитала.
    assert harness.last_text.startswith("✅ Засчитано · +72 XP общий · +72 Здоровье · +72 Спорт")
    assert "💪 «Здоровье» — самый слабый стат: ×1.2 к XP" in harness.last_text
    await harness.tap(ME, texts.WHY_BUTTON)
    assert "• Самый слабый стат: ×1.2" in harness.last_text
    assert "60 мин × 1 × 1 × 1 × 1.2 = 72 XP" in harness.last_text

    # Теперь Здоровье впереди, но пересмотр не отнимает бонус, который был при сдаче.
    async with sessionmaker() as session:
        await _xp(session, await _user(session, seed), seed.sport, 500)
        await session.commit()
    await harness.tap(ME, texts.DISPUTE_BUTTON)
    await harness.send(ME, "Это была полная тренировка")
    # 60 × 0.7 × 1.2 = 50 — поправка −22.
    assert harness.last_text.startswith("⚖️ Пересмотрел. 🟡 Засчитано частично · -22 XP общий")
    async with sessionmaker() as session:
        events = list(await session.scalars(select(XpEvent).where(XpEvent.task_id.is_not(None))))
        assert [(e.amount, e.breakdown["weak_mult"]) for e in events] == [(72, 1.2), (-22, 1.2)]


async def test_stronger_stat_gets_no_bonus(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        await _xp(session, await _user(session, seed), seed.arbitrage, 100)
        await session.commit()
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations.append(verdict("accepted"))

    await _report(sessionmaker, harness, seed, seed.arbitrage)

    assert harness.last_text.startswith("✅ Засчитано · +60 XP общий · +60 Капитал · +60 Арбитраж")
    assert "💪" not in harness.last_text


# Персонаж


async def test_character_levels_from_xp(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    now = datetime.now(UTC)
    long_ago = now.date() - timedelta(days=90)
    async with sessionmaker() as session:
        user = await _user(session, seed)
        capital = await goals.get_active_goal(session, user, seed.capital)
        assert capital is not None
        old = await goals.create_goal(session, user, "Старое направление", None, capital)
        await _xp(session, user, seed.arbitrage, 300)
        await _xp(session, user, old.id, 200, day=long_ago)
        goals.archive_goal(old, now)
        await _xp(session, user, seed.health, 50)
        await _xp(session, user, seed.sport, 100)
        await _xp(session, user, None, 40)  # задача без цели — только в общий уровень
        await session.commit()

        character = await build_character(session, user, now)

    assert character.summary.total.xp == 690
    capital_stat, health_stat = character.stats
    # Стат — цель со всеми направлениями, включая архивные; скилл — только направление.
    assert (capital_stat.level.xp, capital_stat.level.level) == (500, 3)
    assert [(s.goal.title, s.level.level) for s in capital_stat.skills] == [("Арбитраж", 2)]
    assert (health_stat.level.xp, health_stat.season_xp) == (150, 150)
    assert [(s.goal.title, s.level.level) for s in health_stat.skills] == [("Спорт", 2)]
    # За сезон у Капитала 300 (архивное — в прошлом сезоне), у Здоровья 150.
    assert (capital_stat.weakest, health_stat.weakest) == (False, True)
    assert character.last_award is not None
    assert character.last_award.amount == 40
    assert character.last_award.stat is None


async def test_bot_stats_show_stats(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        await _xp(session, await _user(session, seed), seed.arbitrage, 100)
        await session.commit()
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/stats")

    assert "<b>Статы</b>" in harness.last_text
    assert "• Капитал — ур. <b>2</b> (Арбитраж 2)" in harness.last_text
    assert "• Здоровье — ур. <b>1</b> (Спорт 1)\n   ⚠️ самый слабый стат: ×1.2 к XP" in (
        harness.last_text
    )


# Цвет, иконка, «только рост»


def test_palette_matches_api_colors() -> None:
    assert get_args(GoalColor) == PALETTE


async def test_new_goal_takes_free_color(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        capital = await goals.get_active_goal(session, user, seed.capital)
        health = await session.get(Goal, seed.health)
        arbitrage = await session.get(Goal, seed.arbitrage)
        assert capital and health and arbitrage
        assert (capital.color, health.color, arbitrage.color) == ("blue", "orange", None)
        goals.archive_goal(capital, datetime.now(UTC))
        media = await goals.create_goal(session, user, "Медийка", "Аудитория")
        assert media.color == "blue"


async def test_chart_series_use_goal_color(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        health = await session.get(Goal, seed.health)
        assert health is not None
        health.color = "green"
        await _xp(session, user, seed.sport, 30)
        await _xp(session, user, seed.arbitrage, 50)
        config = ChartConfig(metric=Metric.XP, split=Split.GOAL, period=Period.WEEK)
        data = await chart_data(session, user, config, datetime.now(UTC))

    assert {s.name: s.slot for s in data.series} == {"Капитал": 0, "Здоровье": 2}


async def test_growth_only_reaches_agent(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        capital = await session.get(Goal, seed.capital)
        assert capital is not None
        capital.growth_only = True
        await session.flush()
        context = await planning.goal_context(session, user)

    rendered = render_goals(context)
    assert "цель «Капитал». Зачем: Подушка и свобода [только рост]" in rendered
    # Направление цели «только рост» — тоже только про рост.
    assert "направление «Арбитраж». Зачем: не указано [только рост]" in rendered
    assert "цель «Здоровье». Зачем: Энергия\n" in rendered


def test_migration_gives_old_goals_colors(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    config = alembic_config(db)
    command.upgrade(config, "0005")
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO users (id, telegram_id, tz, daily_norm_min, morning_at, evening_at,"
            " day_boundary_hour, freezes_per_week, dashboard_seeded, created_at)"
            " VALUES (1, 1, 'UTC', 120, '09:00:00', '21:00:00', 4, 2, 0, '2026-10-01')"
        )
        for goal_id, parent in [(1, None), (2, 1), (3, None), (4, None)]:
            connection.execute(
                "INSERT INTO goals (id, user_id, parent_id, title, status, created_at)"
                " VALUES (?, 1, ?, 'g', 'active', '2026-10-01')",
                (goal_id, parent),
            )
    command.upgrade(config, "head")
    with sqlite3.connect(db) as connection:
        rows = connection.execute("SELECT id, color, growth_only FROM goals ORDER BY id").fetchall()
    assert rows == [(1, "blue", 0), (2, None, 0), (3, "orange", 0), (4, "green", 0)]


# Веб


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, agent: FakeAgent
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(sessionmaker, ME, tmp_path / "dist", agent, ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


async def test_character_api(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        await _xp(session, await _user(session, seed), seed.arbitrage, 120)
        await session.commit()

    data = (await client.get("/api/character")).json()

    assert data["weak_stat_mult"] == 1.2
    assert data["summary"]["total"]["xp"] == 120
    capital, health = data["stats"]
    assert (capital["title"], capital["color"], capital["level"]["level"]) == ("Капитал", "blue", 2)
    assert capital["skills"] == [
        {
            "id": seed.arbitrage,
            "title": "Арбитраж",
            "level": {"level": 2, "xp": 120, "floor_xp": 100, "next_xp": 364, "progress": 20 / 264},
        }
    ]
    assert (capital["weakest"], health["weakest"]) == (False, True)
    assert data["last_award"]["stat"] == "Капитал"
    assert data["last_award"]["skill"] == "Арбитраж"


async def test_goal_look_and_growth_only(client: httpx.AsyncClient, seed: Seed) -> None:
    response = await client.patch(
        f"/api/goals/{seed.capital}", json={"color": "amber", "icon": "coin", "growth_only": True}
    )
    assert response.status_code == 200
    capital = response.json()[0]
    assert (capital["color"], capital["icon"], capital["growth_only"]) == ("amber", "coin", True)

    reset = (await client.patch(f"/api/goals/{seed.capital}", json={"icon": ""})).json()[0]
    assert reset["icon"] is None

    direction = await client.patch(f"/api/goals/{seed.arbitrage}", json={"growth_only": True})
    assert direction.json()[0]["directions"][0]["growth_only"] is True
    for body in ({"color": "pink"}, {"icon": "coin"}):
        assert (await client.patch(f"/api/goals/{seed.arbitrage}", json=body)).status_code == 422
    for body in ({"color": "#ff00ff"}, {"icon": "<script>"}):
        assert (await client.patch(f"/api/goals/{seed.capital}", json=body)).status_code == 422


async def test_check_reports_where_xp_went(
    client: httpx.AsyncClient,
    agent: FakeAgent,
    sessionmaker: async_sessionmaker[AsyncSession],
    seed: Seed,
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, seed)
        await _xp(session, user, seed.arbitrage, 100)
        fields = TaskFields("Сходить в зал", "Тренировка", seed.sport, 60, 1.0, "обычная работа")
        task = await tasks.create_draft(session, user, fields, "зал", None)
        tasks.save_task(task)
        await session.commit()
        task_id = task.id
    agent.validations.append(verdict("accepted"))

    await client.post(f"/api/tasks/{task_id}/start")
    async with sessionmaker() as session:
        for entry in await session.scalars(select(TimeEntry)):
            entry.started_at -= timedelta(minutes=60)
        await session.commit()
    await client.post(f"/api/tasks/{task_id}/done")
    result = (
        await client.post(f"/api/tasks/{task_id}/report", data={"text": "https://example.com"})
    ).json()

    assert (result["xp_delta"], result["stat"], result["skill"]) == (72, "Здоровье", "Спорт")
    assert result["weak_mult"] == 1.2
    assert result["task"]["breakdown"]["weak_mult"] == 1.2


async def test_levels_api(client: httpx.AsyncClient, seed: Seed) -> None:
    data = (await client.get("/api/levels")).json()

    assert data["steps"][:5] == [
        {"level": 1, "cost": 0, "total": 0},
        {"level": 2, "cost": 100, "total": 100},
        {"level": 3, "cost": 264, "total": 364},
        {"level": 4, "cost": 466, "total": 830},
        {"level": 5, "cost": 696, "total": 1526},
    ]
    assert data["steps"][9]["total"] == 9237
    assert len(data["steps"]) == 30
    assert data["rules"]["validation_mults"] == {"accepted": 1.0, "partial": 0.7, "rejected": 0.0}
    assert (data["rules"]["honor_mode_mult"], data["rules"]["weak_stat_mult"]) == (0.8, 1.2)
    assert data["daily_norm_min"] == 60
