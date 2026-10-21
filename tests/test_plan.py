from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.db.models import DiaryEntry, DiaryStatus, Task, TaskStatus, User
from deepquest.services import plan, tasks
from deepquest.services.days import user_logical_date
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import BotHarness, FakeAgent

ME = 111


@dataclass
class Seed:
    user_id: int
    today: date
    ids: dict[str, int]


async def _task(
    session: AsyncSession,
    user: User,
    title: str,
    status: TaskStatus = TaskStatus.OPEN,
    planned_for: date | None = None,
    minutes: int = 60,
    mult: float = 1.0,
) -> Task:
    task = await tasks.create_draft(
        session, user, TaskFields(title, None, None, minutes, mult, None), title, None
    )
    task.status = status
    task.planned_for = planned_for
    await session.flush()
    return task


@pytest.fixture
async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> Seed:
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.daily_norm_min = 120
        today = user_logical_date(user, now)
        made = {
            "someday": await _task(session, user, "Когда-нибудь"),
            "today": await _task(session, user, "Лендинг", planned_for=today, minutes=90, mult=1.2),
            "running": await _task(
                session, user, "Чекап", TaskStatus.RUNNING, planned_for=today, minutes=60
            ),
            "done": await _task(session, user, "Зал", TaskStatus.DONE, planned_for=today),
            "tomorrow": await _task(
                session, user, "Окулист", planned_for=today + timedelta(days=1)
            ),
            "overdue": await _task(
                session, user, "Стоматолог", planned_for=today - timedelta(days=2)
            ),
            "far": await _task(session, user, "Отпуск", planned_for=today + timedelta(days=20)),
            "draft": await _task(session, user, "Черновик", TaskStatus.DRAFT),
            "old_done": await _task(
                session, user, "Старое", TaskStatus.DONE, planned_for=today - timedelta(days=3)
            ),
        }
        session.add(
            DiaryEntry(
                user_id=user.id,
                text="вяло",
                logical_date=today,
                part_of_day="morning",
                energy=2,
                drive=1,
                emotions=[],
                factors=[],
                status=DiaryStatus.DONE,
            )
        )
        await session.commit()
        return Seed(user.id, today, {name: task.id for name, task in made.items()})


async def _user(session: AsyncSession, seed: Seed) -> User:
    user = await session.get(User, seed.user_id)
    assert user is not None
    return user


async def test_plan_buckets(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    async with sessionmaker() as session:
        week = await plan.build_plan(session, await _user(session, seed), datetime.now(UTC))

    titles = lambda items: [t.title for t in items]  # noqa: E731
    assert week.today == seed.today
    assert len(week.days) == 7
    today, tomorrow = week.days[0], week.days[1]
    # Незакрытые сверху (по ценности), сделанное — в конце и в нагрузку не идёт.
    assert titles(today.tasks) == ["Лендинг", "Чекап", "Зал"]
    assert (today.load_min, today.load_xp) == (150, 168)
    assert titles(tomorrow.tasks) == ["Окулист"]
    assert titles(week.unplanned) == ["Когда-нибудь"]
    assert titles(week.overdue) == ["Стоматолог"]
    # Черновики не в плане, задачи за горизонтом недели — тоже.
    every = [t.title for day in week.days for t in day.tasks] + titles(week.unplanned)
    assert "Черновик" not in every and "Отпуск" not in every and "Старое" not in every
    assert (week.energy_today, week.drive_today) == (2.0, 1.0)


async def test_schedule_rules(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    async with sessionmaker() as session:
        open_task = await session.get(Task, seed.ids["someday"])
        draft = await session.get(Task, seed.ids["draft"])
        done = await session.get(Task, seed.ids["done"])
        assert open_task and draft and done

        plan.schedule(open_task, seed.today + timedelta(days=3), seed.today)
        assert open_task.planned_for == seed.today + timedelta(days=3)
        plan.schedule(open_task, None, seed.today)
        assert open_task.planned_for is None

        for task, day in [
            (draft, seed.today),
            (done, seed.today),
            (open_task, seed.today - timedelta(days=1)),
            (open_task, seed.today + timedelta(days=plan.MAX_AHEAD_DAYS + 1)),
        ]:
            with pytest.raises(plan.PlanError):
                plan.schedule(task, day, seed.today)


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


async def test_plan_api(client: httpx.AsyncClient, seed: Seed) -> None:
    data = (await client.get("/api/plan")).json()

    assert (data["today"], data["norm_min"]) == (seed.today.isoformat(), 120)
    assert [t["title"] for t in data["days"][0]["tasks"]] == ["Лендинг", "Чекап", "Зал"]
    assert data["days"][0]["load_xp"] == 168
    assert [t["title"] for t in data["overdue"]] == ["Стоматолог"]
    assert data["energy_today"] == 2.0

    tomorrow = (seed.today + timedelta(days=1)).isoformat()
    moved = await client.post(f"/api/tasks/{seed.ids['overdue']}/schedule", json={"day": tomorrow})
    assert moved.status_code == 200
    assert moved.json()["planned_for"] == tomorrow
    back = await client.post(f"/api/tasks/{seed.ids['overdue']}/schedule", json={"day": None})
    assert back.json()["planned_for"] is None

    draft = await client.post(f"/api/tasks/{seed.ids['draft']}/schedule", json={"day": tomorrow})
    assert draft.status_code == 409
    missing = await client.post("/api/tasks/9999/schedule", json={"day": tomorrow})
    assert missing.status_code == 404


async def test_bot_today(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/today")

    text = harness.last_text
    assert text.startswith("<b>Сегодня</b> · ~2 ч 30 мин из 2 ч нормы · +168 XP")
    assert "1. Лендинг" in text and "2. ⏱ Чекап" in text
    assert "✓ <s>Зал</s>" in text
    assert "<b>Со вчера и раньше</b>\n3. Стоматолог" in text
    assert "⚠️ Набрано больше нормы на 30 мин." in text
    # Кнопки с номерами открывают задачи — как в бэклоге.
    assert harness.find_button("3")


async def test_bot_today_empty(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        await get_or_create_user(session, ME)
        await session.commit()
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/today")

    assert harness.last_text == texts.TODAY_EMPTY
