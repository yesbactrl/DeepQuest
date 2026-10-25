from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import DiaryAnalysis, DiarySphereNote, ReviewAnalysis
from deepquest.db.models import (
    Report,
    Review,
    SleepKind,
    Task,
    TaskStatus,
    TimeEntry,
    User,
    XpEvent,
    XpKind,
)
from deepquest.services import diary, goals, review, search, sleep, tasks
from deepquest.services.days import season_of
from deepquest.services.proofs import ProofStore
from deepquest.services.review import PeriodKind, period_of
from deepquest.services.sleep import SleepInput
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import FakeAgent, agent_down

ME = 111
# Четверг 22 октября 2026, 09:00 по Москве.
THURSDAY = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)


def state(
    mood: int, factors: tuple[str, ...] = (), goal_id: int | None = None, score: int | None = None
) -> DiaryAnalysis:
    return DiaryAnalysis(
        mood=mood,  # type: ignore[arg-type]
        energy=mood,  # type: ignore[arg-type]
        drive=mood,  # type: ignore[arg-type]
        emotions=[],
        factors=list(factors),
        summary="запись",
        spheres=[DiarySphereNote(goal_id=goal_id, score=score, good="растёт", bad=None)]  # type: ignore[arg-type]
        if goal_id
        else [],
    )


def verdict_text() -> ReviewAnalysis:
    return ReviewAnalysis(
        summary="Неделя ровная.", wins=["+300 XP"], struggles=[], patterns=[], next_steps=["Спать"]
    )


@pytest.fixture
async def user_id(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz = "Europe/Moscow"
        await session.commit()
        return user.id


async def _user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    assert user is not None
    return user


async def _done_task(
    session: AsyncSession, user: User, title: str, goal_id: int | None, at: datetime, xp: int
) -> Task:
    task = await tasks.create_draft(
        session, user, TaskFields(title, None, goal_id, 60, 1.0, None), title, None
    )
    task.status = TaskStatus.DONE
    session.add(
        TimeEntry(
            user_id=user.id, task_id=task.id, started_at=at, ended_at=at + timedelta(minutes=60)
        )
    )
    day = (at + timedelta(hours=3)).date()
    session.add(
        XpEvent(
            user_id=user.id,
            task_id=task.id,
            goal_id=goal_id,
            kind=XpKind.TASK,
            amount=xp,
            # Засчитано 60 минут — по ним фокус; отрезок таймера выше на него не влияет.
            breakdown={"counted_min": 60, "verdict": "accepted"},
            logical_date=day,
            season=season_of(day),
        )
    )
    await session.flush()
    return task


# Периоды


def test_periods() -> None:
    today = date(2026, 10, 22)
    week = period_of(PeriodKind.WEEK, today)
    assert (week.first, week.last, week.label) == (
        date(2026, 10, 19),
        date(2026, 10, 25),
        "19–25 октября",
    )
    before = period_of(PeriodKind.WEEK, today, 3)
    assert before.label == "28 сентября – 4 октября"
    month = period_of(PeriodKind.MONTH, today, 10)
    assert (month.first, month.last, month.label) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
        "Декабрь 2025",
    )
    assert review.previous(period_of(PeriodKind.MONTH, today)).label == "Сентябрь 2026"


# Итоги


async def test_review_counts_week_against_same_days_before(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        health = await goals.create_goal(session, user, "Здоровье", "чтобы жить долго")
        # Эта неделя: пн плохой день с плохим сном, ср хороший с тренировкой.
        agent.diary += [
            state(3, ("плохой сон",)),
            state(8, ("тренировка",), health.id, 7),
            # Прошлая неделя, вторник: сфера была хуже.
            state(5, (), health.id, 4),
            # Прошлая неделя, суббота — за пределами «того же отрезка».
            state(9),
        ]
        monday = THURSDAY - timedelta(days=3)
        await diary.add_entry(session, agent, user, "Разбит", monday)
        await diary.add_entry(session, agent, user, "Бодр", monday + timedelta(days=2))
        await diary.add_entry(session, agent, user, "Так себе", monday - timedelta(days=6))
        await diary.add_entry(session, agent, user, "Отлично", monday - timedelta(days=2))
        await _done_task(session, user, "Зал", health.id, monday + timedelta(days=2), 300)
        await _done_task(session, user, "Мелочь", None, monday + timedelta(days=2), 50)
        await _done_task(session, user, "Старый зал", health.id, monday - timedelta(days=6), 100)

        result = await review.build_review(session, user, PeriodKind.WEEK, 0, THURSDAY)

    assert result.in_progress and result.end == date(2026, 10, 22)
    # 300 + 50 за задачи и по 15 за две записи.
    assert result.totals.xp == 380
    assert (result.totals.done_tasks, result.totals.minutes, result.totals.entries) == (2, 120, 2)
    # До четверга прошлой недели: задача 100 и одна запись; субботняя не считается.
    assert (result.prev_totals.xp, result.prev_totals.entries) == (115, 1)
    assert (result.state.mood, result.prev_state.mood) == (5.5, 5.0)
    [sphere] = result.spheres
    assert (sphere.title, sphere.xp, sphere.prev_xp, sphere.done_tasks) == ("Здоровье", 300, 100, 1)
    assert (sphere.score, sphere.prev_score, sphere.good) == (7.0, 4.0, ["растёт"])
    assert [d.state for d in result.days] == [3.0, None, 8.0, None]
    assert result.bad_days.days == 1 and result.bad_days.factors == [("плохой сон", 1)]
    assert result.good_days.factors == [("тренировка", 1)]
    assert result.good_days.focus_min == 120
    assert [t.title for t in result.top_tasks] == ["Зал", "Мелочь"]
    assert result.top_tasks[0].goal_id == health.id


async def test_past_month_is_complete(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        past = await review.build_review(session, user, PeriodKind.MONTH, 1, THURSDAY)
        assert not past.in_progress and past.period.label == "Сентябрь 2026"


async def test_analysis_is_saved_and_replaced(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.reviews += [
        agent_down(),
        verdict_text(),
        verdict_text().model_copy(update={"summary": "Второй"}),
    ]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        await goals.create_goal(session, user, "Здоровье", "чтобы жить долго")
        result = await review.build_review(session, user, PeriodKind.WEEK, 0, THURSDAY)
        assert not await review.analyze(session, agent, user, result, THURSDAY)
        assert await review.analyze(session, agent, user, result, THURSDAY)
        assert await review.analyze(session, agent, user, result, THURSDAY)
        await session.commit()

        again = await review.build_review(session, user, PeriodKind.WEEK, 0, THURSDAY)
        assert again.analysis is not None and again.analysis.summary == "Второй"
        assert await session.scalar(select(func.count()).select_from(Review)) == 1

    context = agent.review_contexts[0]
    assert context.period == "неделя 19–25 октября (идёт: прошло 4 дн. из 7)"
    assert "Здоровье: XP 0" in context.digest
    assert [goal.title for goal in context.goals] == ["Здоровье"]


# Поиск


async def test_search_tasks_and_diary(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary.append(state(4, ("Ёлка",)))
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        titled = await _done_task(session, user, "Пробежка в парке", None, THURSDAY, 10)
        reported = await _done_task(session, user, "Кардио", None, THURSDAY, 10)
        session.add(
            Report(task_id=reported.id, text="Бегал 5 км по ПАРКУ", proofs=[], honor_mode=True)
        )
        await tasks.create_draft(
            session, user, TaskFields("Парк черновик", None, None, 30, 1.0, None), "т", None
        )
        await diary.add_entry(session, agent, user, "Гулял в парке у ёлки", THURSDAY)
        await session.flush()

        found = await search.search(session, user, "ПАРК")
        assert [hit.task.id for hit in found.tasks] == [titled.id, reported.id]
        assert found.tasks[0].where is None
        assert found.tasks[1].where == "отчёт" and found.tasks[1].snippet == "Бегал 5 км по ПАРКУ"
        assert len(found.entries) == 1
        # «ё» и «е» равны, все слова должны найтись.
        assert len((await search.search(session, user, "елки парке")).entries) == 1
        assert (await search.search(session, user, "парк луна")).tasks == []
        assert (await search.search(session, user, "   ")).tasks == []


def test_snippet_cuts_long_text() -> None:
    text = "а" * 300 + " нужное слово " + "б" * 300
    where, piece = search.snippet([search.Field("отчёт", text)], ["нужное"])  # type: ignore[misc]
    assert where == "отчёт" and piece.startswith("…") and piece.endswith("…")
    assert "нужное" in piece and len(piece) <= search.SNIPPET_LEN + 2


# Веб


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, user_id: int
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeAgent]]:
    agent = FakeAgent()
    app = create_app(sessionmaker, ME, tmp_path / "dist", agent, ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client, agent


async def test_review_and_search_api(client: tuple[httpx.AsyncClient, FakeAgent]) -> None:
    http, agent = client
    got = await http.get("/api/review", params={"kind": "month", "offset": 1})
    assert got.status_code == 200
    body = got.json()
    assert body["kind"] == "month" and body["analysis"] is None and not body["in_progress"]

    agent.reviews.append(verdict_text())
    analyzed = await http.post("/api/review/analyze", params={"kind": "week"})
    assert analyzed.status_code == 200
    assert analyzed.json()["agent_failed"] is False
    assert analyzed.json()["review"]["analysis"]["next_steps"] == ["Спать"]
    assert (await http.get("/api/review")).json()["analysis"]["summary"] == "Неделя ровная."

    assert (await http.get("/api/review", params={"kind": "year"})).status_code == 422

    found = await http.get("/api/search", params={"q": "ничего"})
    assert found.json() == {"tasks": [], "entries": []}


async def test_review_includes_sleep(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        await sleep.add_session(
            session,
            user,
            SleepInput(
                SleepKind.NIGHT, datetime(2026, 10, 20, 0, 30), datetime(2026, 10, 20, 6, 0)
            ),
            THURSDAY,
        )
        result = await review.build_review(session, user, PeriodKind.WEEK, 0, THURSDAY)

    assert result.sleep.days == 1 and result.sleep.avg_total_min == 330
    assert [d.sleep_min for d in result.days] == [None, 330, None, None]
    text = review.digest(result)
    assert "## Сон (норма 8.0 ч" in text and "Отбой в среднем 00:30" in text
