"""Оформление задач агентом: новая мысль, ответ на уточнение, правка карточки.

Перед вызовом модели фиксируем транзакцию: ответ идёт секунды, и всё это время
SQLite не должен держать блокировку записи от этой сессии.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.base import AgentError, TaskAgent
from deepquest.agent.schemas import GoalContext, TaskDraft
from deepquest.db.models import Task, TaskStatus, User
from deepquest.services import goals, tasks
from deepquest.services.agent_log import record_calls

logger = logging.getLogger(__name__)

# Больше задач из одного сообщения — скорее ошибка разбора, чем реальный список дел.
MAX_TASKS_PER_MESSAGE = 5
FALLBACK_QUESTION = "Что именно ты хочешь сделать и что будет результатом?"


@dataclass
class PlanOutcome:
    tasks: list[Task] = field(default_factory=list)
    # Агент задал вопрос: в tasks одна задача в статусе clarifying.
    question: str | None = None
    agent_failed: bool = False


async def goal_context(session: AsyncSession, user: User) -> list[GoalContext]:
    return [
        GoalContext(
            id=goal.id,
            title=goal.title,
            why=goal.why,
            directions=tuple(
                GoalContext(id=d.id, title=d.title, why=d.why) for d in goal.active_children
            ),
        )
        for goal in await goals.list_goals(session, user)
    ]


def _goal_ids(context: list[GoalContext]) -> set[int]:
    return {item.id for goal in context for item in (goal, *goal.directions)}


async def _reload(session: AsyncSession, user: User, items: list[Task]) -> list[Task]:
    reloaded = [await tasks.get_task(session, user, task.id) for task in items]
    return [task for task in reloaded if task is not None]


async def _create_drafts(
    session: AsyncSession,
    user: User,
    drafts: list[TaskDraft],
    source_text: str,
    goal_ids: set[int],
    call_id: int | None,
) -> list[Task]:
    return [
        await tasks.create_draft(
            session, user, tasks.normalize_draft(draft, goal_ids), source_text, call_id
        )
        for draft in drafts[:MAX_TASKS_PER_MESSAGE]
    ]


async def plan_from_text(
    session: AsyncSession, agent: TaskAgent, user: User, text: str
) -> PlanOutcome:
    context = await goal_context(session, user)
    await session.commit()
    try:
        result = await agent.plan_task(text, context)
    except AgentError as exc:
        logger.warning("plan_task failed: %s", exc)
        await record_calls(session, user, exc.calls)
        task = await tasks.create_unestimated(session, user, text)
        return PlanOutcome(await _reload(session, user, [task]), agent_failed=True)

    call_id = await record_calls(session, user, result.calls)
    plan = result.output
    if not plan.tasks:
        question = (plan.clarify_question or "").strip() or FALLBACK_QUESTION
        task = await tasks.create_clarifying(session, user, text, question, call_id)
        return PlanOutcome([task], question=question)

    created = await _create_drafts(session, user, plan.tasks, text, _goal_ids(context), call_id)
    return PlanOutcome(await _reload(session, user, created))


async def answer_clarification(
    session: AsyncSession, agent: TaskAgent, user: User, task: Task, answer: str
) -> PlanOutcome:
    """Ответ на уточняющий вопрос превращает задачу из clarifying в черновик (или несколько)."""
    context = await goal_context(session, user)
    task.clarify_answer = answer
    await session.commit()
    try:
        result = await agent.answer_clarification(
            task.source_text, task.clarify_question or "", answer, context
        )
    except AgentError as exc:
        logger.warning("plan_task answer failed: %s", exc)
        await record_calls(session, user, exc.calls)
        task.status = TaskStatus.DRAFT
        return PlanOutcome(await _reload(session, user, [task]), agent_failed=True)

    call_id = await record_calls(session, user, result.calls)
    goal_ids = _goal_ids(context)
    task.status = TaskStatus.DRAFT
    if not result.output.tasks:
        return PlanOutcome(await _reload(session, user, [task]), agent_failed=True)

    first, *rest = result.output.tasks[:MAX_TASKS_PER_MESSAGE]
    tasks.apply_fields(task, tasks.normalize_draft(first, goal_ids), call_id)
    others = await _create_drafts(session, user, rest, task.source_text, goal_ids, call_id)
    return PlanOutcome(await _reload(session, user, [task, *others]))


async def revise(
    session: AsyncSession, agent: TaskAgent, user: User, task: Task, correction: str | None
) -> bool:
    """Правка карточки по словам пользователя. Без правки — повторная оценка с нуля.

    Возвращает False, если агент не ответил: карточка остаётся прежней.
    """
    context = await goal_context(session, user)
    current = tasks.current_card(task)
    await session.commit()
    try:
        result = await agent.revise_task(task.source_text, current, correction, context)
    except AgentError as exc:
        logger.warning("plan_task revise failed: %s", exc)
        await record_calls(session, user, exc.calls)
        return False
    call_id = await record_calls(session, user, result.calls)
    tasks.apply_fields(task, tasks.normalize_draft(result.output, _goal_ids(context)), call_id)
    return True
