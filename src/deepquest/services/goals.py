from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.db.models import Goal, GoalStatus, User

MAX_TITLE_LEN = 80
MAX_WHY_LEN = 1000
# Цвета статов — те же 8 цветов и в том же порядке, что у графиков (web/src/lib/chartTheme.ts):
# они проверены на контраст в светлой и тёмной теме, поэтому произвольный цвет не задаётся.
PALETTE = ("blue", "orange", "green", "amber", "pink", "forest", "violet", "red")


class GoalError(ValueError):
    """Операция с целью невозможна: чужая, в архиве или нарушает структуру дерева."""


def clean_title(text: str) -> str:
    title = " ".join(text.split())
    if not 1 <= len(title) <= MAX_TITLE_LEN:
        raise ValueError(f"Goal title must be 1..{MAX_TITLE_LEN} chars")
    return title


def clean_why(text: str) -> str:
    why = text.strip()
    if not 1 <= len(why) <= MAX_WHY_LEN:
        raise ValueError(f"Goal why must be 1..{MAX_WHY_LEN} chars")
    return why


async def list_goals(session: AsyncSession, user: User) -> list[Goal]:
    """Активные цели верхнего уровня с подгруженными направлениями."""
    goals = await session.scalars(
        select(Goal)
        .where(
            Goal.user_id == user.id,
            Goal.parent_id.is_(None),
            Goal.status == GoalStatus.ACTIVE,
        )
        .order_by(Goal.id)
        .options(selectinload(Goal.children))
    )
    return list(goals)


async def count_goals(session: AsyncSession, user: User) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Goal)
        .where(
            Goal.user_id == user.id,
            Goal.parent_id.is_(None),
            Goal.status == GoalStatus.ACTIVE,
        )
    )
    return count or 0


async def get_active_goal(session: AsyncSession, user: User, goal_id: int) -> Goal | None:
    """Активная цель или направление пользователя, с родителем и направлениями."""
    return await session.scalar(
        select(Goal)
        .where(Goal.id == goal_id, Goal.user_id == user.id, Goal.status == GoalStatus.ACTIVE)
        .options(selectinload(Goal.children), selectinload(Goal.parent))
    )


async def create_goal(
    session: AsyncSession,
    user: User,
    title: str,
    why: str | None,
    parent: Goal | None = None,
) -> Goal:
    if parent is not None and (
        parent.user_id != user.id or parent.is_direction or parent.status != GoalStatus.ACTIVE
    ):
        raise GoalError(f"Goal {parent.id} cannot have directions")
    if parent is None and why is None:
        raise ValueError("A top-level goal needs a why")
    goal = Goal(
        user_id=user.id,
        parent=parent,
        title=clean_title(title),
        why=clean_why(why) if why is not None else None,
        status=GoalStatus.ACTIVE,
        # Направление берёт цвет своей цели.
        color=None if parent is not None else await _free_color(session, user),
        children=[],
    )
    session.add(goal)
    await session.flush()
    return goal


async def _free_color(session: AsyncSession, user: User) -> str:
    """Первый цвет палитры, который не занят активной целью; если заняты все — по кругу."""
    used = list(
        await session.scalars(
            select(Goal.color).where(
                Goal.user_id == user.id,
                Goal.parent_id.is_(None),
                Goal.status == GoalStatus.ACTIVE,
            )
        )
    )
    free = [color for color in PALETTE if color not in used]
    return free[0] if free else PALETTE[len(used) % len(PALETTE)]


def goal_path(goal: Goal) -> str:
    """«Цель → Направление» или просто «Цель». Родитель должен быть подгружен."""
    return f"{goal.parent.title} → {goal.title}" if goal.parent else goal.title


async def active_goal_ids(session: AsyncSession, user: User) -> set[int]:
    """id всех активных целей и направлений пользователя."""
    ids = await session.scalars(
        select(Goal.id).where(Goal.user_id == user.id, Goal.status == GoalStatus.ACTIVE)
    )
    return set(ids)


def rename_goal(goal: Goal, title: str) -> None:
    goal.title = clean_title(title)


def set_why(goal: Goal, why: str) -> None:
    goal.why = clean_why(why)


def archive_goal(goal: Goal, now: datetime) -> None:
    """Убирает цель в архив вместе с её направлениями. Направления должны быть подгружены."""
    for item in [goal, *goal.active_children]:
        item.status = GoalStatus.ARCHIVED
        item.archived_at = now
