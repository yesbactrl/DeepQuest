from datetime import UTC, datetime

import pytest
from aiogram.methods import AnswerCallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.db.models import Goal, GoalStatus
from deepquest.services import goals
from deepquest.services.users import get_or_create_user
from tests.conftest import BotHarness

ME = 111
WHY = "Хочу не зависеть от зарплаты и пробовать свои идеи"


# Сервис


async def test_goal_needs_why_and_direction_does_not(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        with pytest.raises(ValueError, match="needs a why"):
            await goals.create_goal(session, user, "Свой доход", None)

        goal = await goals.create_goal(session, user, "  Свой   доход ", WHY)
        direction = await goals.create_goal(session, user, "Арбитраж", None, parent=goal)

        assert goal.title == "Свой доход"
        assert direction.parent_id == goal.id
        assert direction.why is None


async def test_tree_is_two_levels_deep(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        goal = await goals.create_goal(session, user, "Свой доход", WHY)
        direction = await goals.create_goal(session, user, "Арбитраж", None, parent=goal)

        with pytest.raises(goals.GoalError):
            await goals.create_goal(session, user, "TikTok", None, parent=direction)


def test_title_length_is_limited() -> None:
    with pytest.raises(ValueError):
        goals.clean_title("x" * (goals.MAX_TITLE_LEN + 1))
    with pytest.raises(ValueError):
        goals.clean_title("   ")


async def test_archive_takes_directions_along(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        income = await goals.create_goal(session, user, "Свой доход", WHY)
        await goals.create_goal(session, user, "Арбитраж", None, parent=income)
        health = await goals.create_goal(session, user, "Здоровье", "Чтобы хватало энергии")
        await session.commit()

        loaded = await goals.get_active_goal(session, user, income.id)
        assert loaded is not None
        goals.archive_goal(loaded, datetime.now(UTC))
        await session.commit()

        assert [g.id for g in await goals.list_goals(session, user)] == [health.id]
        assert await goals.count_goals(session, user) == 1
        statuses = await session.scalars(select(Goal.status).where(Goal.id != health.id))
        assert set(statuses) == {GoalStatus.ARCHIVED}


# Бот


async def _onboard(harness: BotHarness) -> None:
    for step in ("/start", "+7", "60", "9", "21"):
        await harness.send(ME, step)
    assert harness.last_text == texts.ASK_GOAL_TITLE


async def _create_income_goal(harness: BotHarness) -> None:
    await _onboard(harness)
    await harness.send(ME, "Свой доход")
    await harness.send(ME, WHY)


async def _goals_in_db(sessionmaker: async_sessionmaker[AsyncSession]) -> list[Goal]:
    async with sessionmaker() as session:
        return list(await session.scalars(select(Goal).order_by(Goal.id)))


async def test_first_goal_right_after_onboarding(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _onboard(harness)

    await harness.send(ME, "Свой доход")
    assert harness.last_text == texts.ask_goal_why("Свой доход")
    assert harness.screens[-1].reply_markup is None  # у цели «зачем» не пропустить

    await harness.send(ME, WHY)
    assert harness.last_text.startswith(texts.GOAL_SAVED)
    assert WHY in harness.last_text
    harness.button(texts.NEW_DIRECTION_BUTTON)
    harness.button(texts.ANOTHER_GOAL_BUTTON)

    [goal] = await _goals_in_db(sessionmaker)
    assert (goal.title, goal.why, goal.parent_id) == ("Свой доход", WHY, None)


async def test_direction_with_skipped_why(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _create_income_goal(harness)

    await harness.tap(ME, texts.NEW_DIRECTION_BUTTON)
    assert harness.last_text == texts.ask_direction_title("Свой доход")
    await harness.send(ME, "Арбитраж трафика")
    await harness.tap(ME, texts.SKIP_BUTTON)

    assert harness.last_text.startswith(texts.DIRECTION_SAVED)
    assert "• Арбитраж трафика" in harness.last_text
    goal, direction = await _goals_in_db(sessionmaker)
    assert (direction.parent_id, direction.why) == (goal.id, None)


async def test_goals_list_and_cards(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _create_income_goal(harness)
    await harness.tap(ME, texts.NEW_DIRECTION_BUTTON)
    await harness.send(ME, "Рилсы")
    await harness.send(ME, "Чтобы набрать аудиторию")

    await harness.send(ME, "/goals")
    assert "1. <b>Свой доход</b>" in harness.last_text
    assert WHY in harness.last_text
    assert "• Рилсы" in harness.last_text

    await harness.tap(ME, "1. Свой доход")
    assert harness.last_text.startswith("🎯 <b>Свой доход</b>")

    await harness.tap(ME, "🧭 Рилсы")
    assert "Направление цели «Свой доход»" in harness.last_text
    assert "Чтобы набрать аудиторию" in harness.last_text

    await harness.tap(ME, "← Свой доход")
    await harness.tap(ME, texts.ALL_GOALS_BUTTON)
    assert harness.last_text.startswith("<b>Цели</b>")


async def test_rename_and_edit_why(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _create_income_goal(harness)

    await harness.tap(ME, texts.RENAME_BUTTON)
    assert harness.last_text == texts.ask_rename("Свой доход")
    await harness.send(ME, "Доход вне найма")
    assert harness.last_text.startswith(texts.GOAL_UPDATED)

    await harness.tap(ME, texts.EDIT_WHY_BUTTON)
    await harness.send(ME, "Свобода выбирать проекты")

    [goal] = await _goals_in_db(sessionmaker)
    assert (goal.title, goal.why) == ("Доход вне найма", "Свобода выбирать проекты")


async def test_invalid_answers_keep_the_step(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _onboard(harness)

    await harness.send(ME, "x" * (goals.MAX_TITLE_LEN + 1))
    assert harness.last_text == texts.GOAL_TITLE_INVALID

    await harness.send(ME, "Здоровье")
    assert harness.last_text == texts.ask_goal_why("Здоровье")


async def test_cancel_goal_creation(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _onboard(harness)
    await harness.send(ME, "Здоровье")

    await harness.send(ME, "/cancel")

    assert harness.last_text == texts.CANCELLED
    assert await _goals_in_db(sessionmaker) == []


async def test_archive_with_confirmation(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _create_income_goal(harness)
    await harness.tap(ME, texts.NEW_DIRECTION_BUTTON)
    await harness.send(ME, "Арбитраж трафика")
    await harness.tap(ME, texts.SKIP_BUTTON)
    open_goal_button = harness.button(texts.RENAME_BUTTON)

    await harness.tap(ME, texts.ARCHIVE_BUTTON)
    assert "направления тоже уйдут в архив" in harness.last_text
    await harness.tap(ME, texts.ARCHIVE_YES_BUTTON)

    assert harness.last_text == texts.GOALS_EMPTY
    assert {g.status for g in await _goals_in_db(sessionmaker)} == {GoalStatus.ARCHIVED}

    # Старые кнопки архивной цели больше не работают.
    await harness.press(ME, open_goal_button)
    answer = harness.telegram.requests[-1]
    assert isinstance(answer, AnswerCallbackQuery)
    assert answer.text == texts.GOAL_NOT_FOUND


async def test_archive_direction_returns_to_goal(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _create_income_goal(harness)
    await harness.tap(ME, texts.NEW_DIRECTION_BUTTON)
    await harness.send(ME, "Арбитраж трафика")
    await harness.tap(ME, texts.SKIP_BUTTON)

    await harness.tap(ME, "🧭 Арбитраж трафика")
    await harness.tap(ME, texts.ARCHIVE_BUTTON)
    await harness.tap(ME, texts.ARCHIVE_YES_BUTTON)

    assert harness.last_text.startswith("🎯 <b>Свой доход</b>")
    assert "• Арбитраж" not in harness.last_text
    goal, direction = await _goals_in_db(sessionmaker)
    assert (goal.status, direction.status) == (GoalStatus.ACTIVE, GoalStatus.ARCHIVED)
