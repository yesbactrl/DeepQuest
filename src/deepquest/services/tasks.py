from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.agent.schemas import VALUE_MULTIPLIERS, CurrentTask, TaskDraft
from deepquest.db.models import Goal, Task, TaskStatus, User

MAX_TITLE_LEN = 200
MIN_ESTIMATE_MIN = 5
MAX_ESTIMATE_MIN = 8 * 60


class TaskError(ValueError):
    """Действие недоступно в текущем статусе задачи."""


@dataclass(frozen=True)
class TaskFields:
    """Оценка задачи после проверки: то, что ушло в базу из ответа агента."""

    title: str
    expected_result: str | None
    goal_id: int | None
    estimate_min: int
    value_mult: float
    mult_reason: str | None


def _short_title(text: str) -> str:
    title = " ".join(text.split())
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 1].rstrip() + "…"
    return title or "Без названия"


def normalize_draft(draft: TaskDraft, goal_ids: Collection[int]) -> TaskFields:
    """Агенту не доверяем вслепую: чужой id цели, странная оценка или множитель вне шкалы
    приводятся к допустимым значениям."""
    estimate = round(draft.estimate_min / 5) * 5
    return TaskFields(
        title=_short_title(draft.title),
        expected_result=draft.expected_result.strip() or None,
        goal_id=draft.goal_id if draft.goal_id in goal_ids else None,
        estimate_min=min(max(estimate, MIN_ESTIMATE_MIN), MAX_ESTIMATE_MIN),
        value_mult=min(VALUE_MULTIPLIERS, key=lambda mult: abs(mult - draft.value_mult)),
        mult_reason=draft.mult_reason.strip() or None,
    )


def current_card(task: Task) -> CurrentTask:
    return CurrentTask(
        title=task.title,
        expected_result=task.expected_result,
        goal_id=task.goal_id,
        estimate_min=task.estimate_min,
        value_mult=task.value_mult,
        mult_reason=task.mult_reason,
    )


async def get_task(session: AsyncSession, user: User, task_id: int) -> Task | None:
    """Задача с целью и родителем цели. Перечитывает уже загруженные объекты:
    после правки goal_id связь `goal` иначе осталась бы старой."""
    return await session.scalar(
        select(Task)
        .where(Task.id == task_id, Task.user_id == user.id)
        .options(selectinload(Task.goal).selectinload(Goal.parent))
        .execution_options(populate_existing=True)
    )


async def list_tasks(
    session: AsyncSession,
    user: User,
    statuses: Collection[TaskStatus] | None = None,
    goal_ids: Collection[int] | None = None,
) -> list[Task]:
    """Задачи для веба: свежие сверху, с целью и её родителем."""
    query = (
        select(Task)
        .where(Task.user_id == user.id)
        .order_by(Task.updated_at.desc(), Task.id.desc())
        .options(selectinload(Task.goal).selectinload(Goal.parent))
    )
    if statuses:
        query = query.where(Task.status.in_(list(statuses)))
    if goal_ids:
        query = query.where(Task.goal_id.in_(list(goal_ids)))
    return list(await session.scalars(query))


async def list_backlog(session: AsyncSession, user: User) -> list[Task]:
    """Задачи в работе: открытые и та, по которой сейчас идёт таймер."""
    tasks = await session.scalars(
        select(Task)
        .where(Task.user_id == user.id, Task.status.in_([TaskStatus.OPEN, TaskStatus.RUNNING]))
        .order_by(Task.value_mult.desc().nulls_last(), Task.created_at)
        .options(selectinload(Task.goal).selectinload(Goal.parent))
    )
    return list(tasks)


async def last_awaiting_report(session: AsyncSession, user: User) -> Task | None:
    task_id = await session.scalar(
        select(Task.id)
        .where(Task.user_id == user.id, Task.status == TaskStatus.AWAITING_REPORT)
        .order_by(Task.updated_at.desc())
        .limit(1)
    )
    return await get_task(session, user, task_id) if task_id is not None else None


async def _add(session: AsyncSession, task: Task) -> Task:
    session.add(task)
    await session.flush()
    return task


async def create_draft(
    session: AsyncSession,
    user: User,
    fields: TaskFields,
    source_text: str,
    agent_call_id: int | None,
) -> Task:
    task = Task(user_id=user.id, status=TaskStatus.DRAFT, source_text=source_text)
    apply_fields(task, fields, agent_call_id)
    return await _add(session, task)


async def create_unestimated(session: AsyncSession, user: User, source_text: str) -> Task:
    """Черновик без оценки: агент недоступен, но мысль не должна потеряться."""
    task = Task(
        user_id=user.id,
        status=TaskStatus.DRAFT,
        source_text=source_text,
        title=_short_title(source_text),
    )
    return await _add(session, task)


async def create_clarifying(
    session: AsyncSession,
    user: User,
    source_text: str,
    question: str,
    agent_call_id: int | None,
) -> Task:
    task = Task(
        user_id=user.id,
        status=TaskStatus.CLARIFYING,
        source_text=source_text,
        title=_short_title(source_text),
        clarify_question=question,
        agent_call_id=agent_call_id,
    )
    return await _add(session, task)


def apply_fields(task: Task, fields: TaskFields, agent_call_id: int | None) -> None:
    task.title = fields.title
    task.expected_result = fields.expected_result
    task.goal_id = fields.goal_id
    task.estimate_min = fields.estimate_min
    task.value_mult = fields.value_mult
    task.mult_reason = fields.mult_reason
    task.agent_call_id = agent_call_id


def save_task(task: Task) -> None:
    if task.status != TaskStatus.DRAFT:
        raise TaskError(f"Task {task.id} is {task.status}, not a draft")
    task.status = TaskStatus.OPEN


def cancel_task(task: Task) -> None:
    if task.status not in {TaskStatus.CLARIFYING, TaskStatus.DRAFT, TaskStatus.OPEN}:
        raise TaskError(f"Task {task.id} is {task.status}, cannot cancel")
    task.status = TaskStatus.CANCELLED
