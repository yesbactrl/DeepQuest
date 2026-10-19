from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import PlanResult, TasksResult
from deepquest.bot import texts
from deepquest.db.models import AgentCall, Task, TaskStatus
from deepquest.services import goals, tasks
from deepquest.services.users import get_or_create_user
from tests.conftest import BotHarness, FakeAgent, agent_down, draft

ME = 111
THOUGHT = "Короче, надо попробовать запустить одну кампанию в тиктоке, баксов на двадцать"


@dataclass
class Seed:
    income: int
    arbitrage: int
    health: int


@pytest.fixture
async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> Seed:
    """Пользователь прошёл онбординг и завёл цели."""
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.onboarded_at = datetime.now(UTC)
        income = await goals.create_goal(session, user, "Свой доход", "Не зависеть от зарплаты")
        arbitrage = await goals.create_goal(session, user, "Арбитраж трафика", None, income)
        health = await goals.create_goal(session, user, "Здоровье", "Чтобы хватало энергии")
        await session.commit()
        return Seed(income.id, arbitrage.id, health.id)


async def _tasks(sessionmaker: async_sessionmaker[AsyncSession]) -> list[Task]:
    async with sessionmaker() as session:
        return list(await session.scalars(select(Task).order_by(Task.id)))


def _harness(sessionmaker: async_sessionmaker[AsyncSession]) -> tuple[BotHarness, FakeAgent]:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    return harness, harness.agent


# Нормализация ответа агента


def test_agent_output_is_normalized() -> None:
    fields = tasks.normalize_draft(
        draft("  Запустить   кампанию ", goal_id=999, minutes=2000, mult=1.5), goal_ids={1, 2}
    )
    assert fields.title == "Запустить кампанию"
    assert fields.goal_id is None
    assert fields.estimate_min == tasks.MAX_ESTIMATE_MIN
    assert fields.value_mult == 1.5

    assert tasks.normalize_draft(draft("x", minutes=52), {1}).estimate_min == 50
    assert tasks.normalize_draft(draft("x", minutes=0), {1}).estimate_min == tasks.MIN_ESTIMATE_MIN


# Новая мысль → карточка


async def test_text_becomes_task_card(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(
        PlanResult(
            clarify_question=None,
            tasks=[
                draft(
                    "Запустить тестовую кампанию в TikTok с бюджетом $20",
                    goal_id=seed.arbitrage,
                    minutes=180,
                    mult=1.5,
                    reason="реальный шаг, некомфортно",
                )
            ],
        )
    )

    await harness.send(ME, THOUGHT)

    placeholder, card = harness.screens[-2:]
    assert placeholder.text == texts.PLANNING
    assert isinstance(card, EditMessageText)
    assert card.message_id == harness.telegram.message_id_of(placeholder)
    assert "Запустить тестовую кампанию в TikTok" in card.text
    assert "Свой доход → Арбитраж трафика" in card.text
    assert "3 ч" in card.text
    assert "×1.5 — реальный шаг, некомфортно" in card.text
    harness.button(texts.SAVE_BUTTON)

    [call] = agent.calls
    assert call[1]["text"] == THOUGHT
    assert [g.title for g in call[1]["goals"]] == ["Свой доход", "Здоровье"]
    assert call[1]["goals"][0].directions[0].id == seed.arbitrage

    [task] = await _tasks(sessionmaker)
    assert (task.status, task.source_text, task.estimate_min) == (TaskStatus.DRAFT, THOUGHT, 180)
    async with sessionmaker() as session:
        call_row = await session.get(AgentCall, task.agent_call_id)
        assert call_row is not None and call_row.kind == "plan_task"


async def test_one_message_many_tasks(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(
        PlanResult(clarify_question=None, tasks=[draft("Записать рилс"), draft("Сходить в зал")])
    )

    await harness.send(ME, "записать рилс и сходить в зал")

    assert "Записать рилс" in harness.screens[-2].text
    assert "Сходить в зал" in harness.last_text
    assert [t.status for t in await _tasks(sessionmaker)] == [TaskStatus.DRAFT] * 2


async def test_save_puts_task_into_backlog(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(PlanResult(clarify_question=None, tasks=[draft("Записать рилс")]))
    await harness.send(ME, "записать рилс")

    await harness.tap(ME, texts.SAVE_BUTTON)
    assert texts.TASK_SAVED in harness.last_text
    assert harness.screens[-1].reply_markup is None

    await harness.send(ME, "/backlog")
    assert "1 задача" in harness.last_text
    assert "1. Записать рилс" in harness.last_text
    [task] = await _tasks(sessionmaker)
    assert task.status == TaskStatus.OPEN


async def test_cancel_draft(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(PlanResult(clarify_question=None, tasks=[draft("Записать рилс")]))
    await harness.send(ME, "записать рилс")

    await harness.tap(ME, texts.CANCEL_TASK_BUTTON)

    assert texts.TASK_CANCELLED in harness.last_text
    [task] = await _tasks(sessionmaker)
    assert task.status == TaskStatus.CANCELLED


async def test_not_onboarded_user_is_not_planned(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness, agent = _harness(sessionmaker)

    await harness.send(ME, "записать рилс")

    assert harness.last_text == texts.NEED_ONBOARDING
    assert agent.calls == []


# Уточнение


async def test_clarifying_question_then_answer(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    question = "Что будет результатом? Запущенная кампания или просто изучение?"
    agent.plans.append(PlanResult(clarify_question=question, tasks=[]))
    agent.answers.append(TasksResult(tasks=[draft("Запустить кампанию", seed.arbitrage)]))

    await harness.send(ME, "поизучать тикток")
    assert harness.last_text == texts.clarify_question(question)
    question_id = harness.telegram.message_id_of(harness.screens[-1])
    [task] = await _tasks(sessionmaker)
    assert task.status == TaskStatus.CLARIFYING

    await harness.send(ME, "запустить кампанию")

    assert agent.calls[-1] == (
        "answer",
        {"text": "поизучать тикток", "question": question, "answer": "запустить кампанию"},
    )
    assert "Запустить кампанию" in harness.last_text
    dropped = [r for r in harness.telegram.requests if isinstance(r, EditMessageReplyMarkup)]
    assert [r.message_id for r in dropped] == [question_id]
    [task] = await _tasks(sessionmaker)
    assert (task.status, task.clarify_answer) == (TaskStatus.DRAFT, "запустить кампанию")


async def test_cancel_while_clarifying(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(PlanResult(clarify_question="Что сделать?", tasks=[]))
    await harness.send(ME, "привет")

    await harness.send(ME, "/cancel")

    assert harness.last_text == texts.CANCELLED
    [task] = await _tasks(sessionmaker)
    assert task.status == TaskStatus.CANCELLED


# Правка


async def test_correction_updates_card(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(
        PlanResult(clarify_question=None, tasks=[draft("Запустить кампанию", minutes=120)])
    )
    agent.revisions.append(draft("Запустить кампанию", goal_id=seed.arbitrage, minutes=240))
    await harness.send(ME, THOUGHT)
    old_card_id = harness.find_button(texts.EDIT_TASK_BUTTON)[1]

    await harness.tap(ME, texts.EDIT_TASK_BUTTON)
    assert harness.last_text == texts.ASK_CORRECTION
    await harness.send(ME, "не 2 часа, а 4, и это арбитраж")

    name, args = agent.calls[-1]
    assert (name, args["correction"]) == ("revise", "не 2 часа, а 4, и это арбитраж")
    assert args["current"].estimate_min == 120
    assert "4 ч" in harness.last_text
    assert "Свой доход → Арбитраж трафика" in harness.last_text
    harness.button(texts.SAVE_BUTTON)
    dropped = [r for r in harness.telegram.requests if isinstance(r, EditMessageReplyMarkup)]
    assert [r.message_id for r in dropped] == [old_card_id]


async def test_failed_correction_keeps_card(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(PlanResult(clarify_question=None, tasks=[draft("Записать рилс")]))
    agent.revisions.append(agent_down())
    await harness.send(ME, "записать рилс")
    await harness.tap(ME, texts.EDIT_TASK_BUTTON)

    await harness.send(ME, "на 3 часа")

    assert harness.last_text == texts.AGENT_FAILED_REVISE
    [task] = await _tasks(sessionmaker)
    assert task.estimate_min == 60
    # Старая карточка осталась рабочей.
    harness.button(texts.SAVE_BUTTON, on="Записать рилс")


# Агент недоступен


async def test_agent_down_keeps_thought_and_offers_retry(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(agent_down())
    agent.revisions.append(draft("Запустить кампанию", seed.arbitrage, minutes=180, mult=1.5))

    await harness.send(ME, THOUGHT)

    assert harness.last_text.startswith(texts.AGENT_FAILED)
    assert texts.NO_ESTIMATE in harness.last_text
    [task] = await _tasks(sessionmaker)
    assert (task.status, task.estimate_min, task.title) == (TaskStatus.DRAFT, None, THOUGHT)
    async with sessionmaker() as session:
        [error] = await session.scalars(select(AgentCall.error))
        assert error == "API down"

    await harness.tap(ME, texts.RETRY_BUTTON)

    name, args = agent.calls[-1]
    assert (name, args["correction"]) == ("revise", None)
    assert "×1.5" in harness.last_text
    assert texts.AGENT_FAILED not in harness.last_text
    [task] = await _tasks(sessionmaker)
    assert task.is_estimated


# Бэклог


async def test_backlog_open_and_remove(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(
        PlanResult(
            clarify_question=None,
            tasks=[
                draft("Сходить в зал", seed.health, mult=1.0),
                draft("Позвонить клиенту", mult=1.5),
            ],
        )
    )
    await harness.send(ME, "зал и звонок")
    await harness.tap(ME, texts.SAVE_BUTTON, on="Сходить в зал")
    await harness.tap(ME, texts.SAVE_BUTTON, on="Позвонить клиенту")

    await harness.send(ME, "/backlog")
    # Сначала самое ценное.
    assert harness.last_text.index("Позвонить клиенту") < harness.last_text.index("Сходить в зал")

    await harness.tap(ME, "2")
    assert "Сходить в зал" in harness.last_text
    await harness.tap(ME, texts.REMOVE_TASK_BUTTON)
    assert harness.last_text.startswith(texts.TASK_REMOVED)
    assert "Сходить в зал" in harness.last_text

    await harness.tap(ME, texts.BACKLOG_BUTTON)
    assert "1 задача" in harness.last_text
    statuses = {t.title: t.status for t in await _tasks(sessionmaker)}
    assert statuses == {"Сходить в зал": TaskStatus.CANCELLED, "Позвонить клиенту": TaskStatus.OPEN}


async def test_empty_backlog(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    harness, _ = _harness(sessionmaker)

    await harness.send(ME, "/backlog")

    assert harness.last_text == texts.BACKLOG_EMPTY


async def test_buttons_of_cancelled_task_are_stale(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness, agent = _harness(sessionmaker)
    agent.plans.append(PlanResult(clarify_question=None, tasks=[draft("Записать рилс")]))
    await harness.send(ME, "записать рилс")
    save = harness.find_button(texts.SAVE_BUTTON)
    await harness.tap(ME, texts.CANCEL_TASK_BUTTON)

    await harness.press(ME, *save)

    answer = harness.telegram.requests[-1]
    assert getattr(answer, "text", None) == texts.STALE_BUTTON
    [task] = await _tasks(sessionmaker)
    assert task.status == TaskStatus.CANCELLED
