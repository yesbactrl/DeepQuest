from datetime import UTC, date, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import DiaryAnalysis
from deepquest.db.models import SleepKind, TaskStatus
from deepquest.mcp_server import SOURCE_MARK, Advisor, AdvisorError, build_server
from deepquest.services import goals, sleep, tasks
from deepquest.services.sleep import SleepInput
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from tests.conftest import FakeAgent

ME = 111
# Суббота 24 октября 2026, 12:00 по Москве.
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


@pytest.fixture
async def advisor(sessionmaker: async_sessionmaker[AsyncSession]) -> tuple[Advisor, FakeAgent]:
    agent = FakeAgent()
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz = "Europe/Moscow"
        health = await goals.create_goal(session, user, "Здоровье", "чтобы жить долго")
        task = await tasks.create_draft(
            session,
            user,
            TaskFields("Сходить в зал", "тренировка", health.id, 60, 1.2, None),
            "зал",
            None,
        )
        tasks.save_task(task)
        task.planned_for = date(2026, 10, 24)
        await sleep.add_session(
            session,
            user,
            SleepInput(
                SleepKind.NIGHT, datetime(2026, 10, 24, 0, 30), datetime(2026, 10, 24, 8, 0), 7
            ),
            NOW,
        )
        await session.commit()
    return Advisor(sessionmaker, ME, agent, clock=lambda: NOW), agent


async def test_overview_shows_day_plan_sleep_and_goals(advisor: tuple[Advisor, FakeAgent]) -> None:
    text = await advisor[0].overview()
    assert "Сейчас 24.10.2026 12:00 (сб)" in text
    assert "«Сходить в зал» — в бэклоге; Здоровье; оценка 1 ч 00 мин, ×1.2; на 24.10 (сб)" in text
    assert "Сон сегодня: 7 ч 30 мин (норма 8 ч 00 мин), лёг 00:30, встал 08:00" in text
    assert "- 1: Здоровье" in text


async def test_reading_tools(advisor: tuple[Advisor, FakeAgent]) -> None:
    a = advisor[0]
    assert "Сходить в зал" in await a.list_tasks("backlog")
    assert await a.list_tasks("done") == "Задач нет."
    with pytest.raises(AdvisorError):
        await a.list_tasks("nope")
    assert "Результат: тренировка" in await a.get_task(1)
    with pytest.raises(AdvisorError, match="#99"):
        await a.get_task(99)
    assert "24.10 (сб): 1 ч 00 мин, 72 XP" in await a.get_plan(2)
    assert "зачем: чтобы жить долго" in await a.list_goals()
    assert "ночь 00:30–08:00 (качество 7)" in await a.get_sleep(7)
    assert "# Итоги: неделя 19–25 октября" in await a.get_review("week")
    assert "Сходить в зал" in await a.search("ЗАЛ")
    assert await a.get_diary(7) == "Записей за этот период нет."


async def test_actions(
    advisor: tuple[Advisor, FakeAgent], sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    a, agent = advisor
    created = await a.create_task("Пробежка 5 км", "пробежал", 47, 1.3, 1, date(2026, 10, 25))
    # Оценка округляется до 5 минут, множитель — к ближайшему на шкале.
    assert "#2 «Пробежка 5 км» — в бэклоге; Здоровье; оценка 45 мин, ×1.2; на 25.10 (вс)" in created
    with pytest.raises(AdvisorError, match="60 дней"):
        await a.create_task("Далеко", "x", 30, planned_for=date(2027, 6, 1))
    assert "без дня" in await a.schedule_task(2, None)

    agent.diary.append(
        DiaryAnalysis(mood=6, energy=7, drive=5, emotions=[], factors=["зал"], summary="Норм")  # type: ignore[arg-type]
    )
    saved = await a.add_diary_entry("Сходил в зал, норм")
    assert "+15 XP" in saved and "настроение 6" in saved

    with pytest.raises(AdvisorError, match="Пересекается"):
        await a.log_sleep(datetime(2026, 10, 24, 7, 0), datetime(2026, 10, 24, 9, 0))
    assert "1 ч 00 мин" in await a.log_sleep(
        datetime(2026, 10, 24, 10, 0), datetime(2026, 10, 24, 11, 0), "nap", note="после зала"
    )

    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        task = await tasks.get_task(session, user, 2)
        assert task is not None and task.status == TaskStatus.OPEN
        assert task.source_text.startswith(SOURCE_MARK)


async def test_server_lists_tools_and_turns_errors_into_text(
    advisor: tuple[Advisor, FakeAgent],
) -> None:
    server = build_server(advisor[0])
    names = {tool.name for tool in await server.list_tools()}
    assert {"overview", "list_tasks", "get_sleep", "create_task", "log_sleep"} <= names

    # Ошибку инструмента протокол отдаёт модели текстом с is_error.
    with pytest.raises(ToolError, match="Задачи #99 нет."):
        await server.call_tool("get_task", {"task_id": 99})

    ok = await server.call_tool("schedule_task", {"task_id": 1, "day": "2026-10-26"})
    assert not ok.is_error and "26.10 (пн)" in ok.content[0].text  # type: ignore[union-attr]


async def test_memory_tools(advisor: tuple[Advisor, FakeAgent]) -> None:
    a = advisor[0]
    assert "Запомнил (#1): Лучше работается после 11" in await a.remember(
        "Лучше работается после 11"
    )
    assert "- #1: Лучше работается после 11" in await a.overview()
    assert await a.forget(1) == "Забыл заметку #1."
    with pytest.raises(AdvisorError, match="#1"):
        await a.forget(1)
