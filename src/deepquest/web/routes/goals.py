"""Цели и направления. Каждое изменение возвращает весь список: фронтенду проще."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import Goal, User
from deepquest.services import goals, stats
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import GoalCreate, GoalOut, GoalUpdate

router = APIRouter(prefix="/api/goals", tags=["goals"])

TITLE_INVALID = f"Название — от 1 до {MAX_TITLE_LEN} символов."
WHY_INVALID = f"«Зачем» — до {MAX_WHY_LEN} символов."
WHY_REQUIRED = "У цели должно быть «зачем»: по нему агент оценивает задачи."
GOAL_NOT_FOUND = "Цель не найдена: возможно, она уже в архиве."
NESTED_DIRECTION = "Направление добавляется только к цели, а не к другому направлению."


async def _goal_list(session: AsyncSession, user: User) -> list[GoalOut]:
    items = await goals.list_goals(session, user)
    numbers = await stats.goal_stats(session, user, items, datetime.now(UTC))
    return [GoalOut.of(goal, numbers) for goal in items]


async def _active_goal(session: AsyncSession, user: User, goal_id: int) -> Goal:
    goal = await goals.get_active_goal(session, user, goal_id)
    if goal is None:
        raise HTTPException(404, GOAL_NOT_FOUND)
    return goal


def _clean_title(text: str) -> str:
    try:
        return goals.clean_title(text)
    except ValueError:
        raise HTTPException(422, TITLE_INVALID) from None


def _clean_why(text: str | None) -> str | None:
    if text is None or not text.strip():
        return None
    try:
        return goals.clean_why(text)
    except ValueError:
        raise HTTPException(422, WHY_INVALID) from None


@router.get("")
async def list_goals(session: SessionDep, user: UserDep) -> list[GoalOut]:
    return await _goal_list(session, user)


@router.post("", status_code=201)
async def create_goal(body: GoalCreate, session: SessionDep, user: UserDep) -> list[GoalOut]:
    parent = await _active_goal(session, user, body.parent_id) if body.parent_id else None
    title, why = _clean_title(body.title), _clean_why(body.why)
    if parent is None and why is None:
        raise HTTPException(422, WHY_REQUIRED)
    try:
        await goals.create_goal(session, user, title, why, parent)
    except goals.GoalError:
        raise HTTPException(409, NESTED_DIRECTION) from None
    return await _goal_list(session, user)


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: int, body: GoalUpdate, session: SessionDep, user: UserDep
) -> list[GoalOut]:
    goal = await _active_goal(session, user, goal_id)
    if body.title is not None:
        goal.title = _clean_title(body.title)
    if body.why is not None:
        why = _clean_why(body.why)
        if why is None and not goal.is_direction:
            raise HTTPException(422, WHY_REQUIRED)
        goal.why = why
    return await _goal_list(session, user)


@router.post("/{goal_id}/archive")
async def archive_goal(goal_id: int, session: SessionDep, user: UserDep) -> list[GoalOut]:
    goal = await _active_goal(session, user, goal_id)
    goals.archive_goal(goal, datetime.now(UTC))
    return await _goal_list(session, user)
