"""Схемы веб-API: что фронтенд отправляет и получает."""

from datetime import datetime, time

from pydantic import BaseModel, Field

from deepquest.db.models import Goal, GoalStatus, User
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN
from deepquest.services.stats import GoalStats


class MeOut(BaseModel):
    tz: str
    daily_norm_min: int
    morning_at: time
    evening_at: time
    day_boundary_hour: int
    onboarded: bool

    @classmethod
    def of(cls, user: User) -> MeOut:
        return cls(
            tz=user.tz,
            daily_norm_min=user.daily_norm_min,
            morning_at=user.morning_at,
            evening_at=user.evening_at,
            day_boundary_hour=user.day_boundary_hour,
            onboarded=user.onboarded_at is not None,
        )


class GoalStatsOut(BaseModel):
    minutes: int
    xp: int
    done_tasks: int
    last_activity_at: datetime | None
    idle_days: int

    @classmethod
    def of(cls, stats: GoalStats) -> GoalStatsOut:
        return cls(
            minutes=stats.minutes,
            xp=stats.xp,
            done_tasks=stats.done_tasks,
            last_activity_at=stats.last_activity_at,
            idle_days=stats.idle_days,
        )


class DirectionOut(BaseModel):
    id: int
    title: str
    why: str | None
    created_at: datetime
    stats: GoalStatsOut


class GoalOut(BaseModel):
    id: int
    title: str
    why: str | None
    status: GoalStatus
    created_at: datetime
    stats: GoalStatsOut
    directions: list[DirectionOut]

    @classmethod
    def of(cls, goal: Goal, stats: dict[int, GoalStats]) -> GoalOut:
        return cls(
            id=goal.id,
            title=goal.title,
            why=goal.why,
            status=goal.status,
            created_at=goal.created_at,
            stats=GoalStatsOut.of(stats[goal.id]),
            directions=[
                DirectionOut(
                    id=d.id,
                    title=d.title,
                    why=d.why,
                    created_at=d.created_at,
                    stats=GoalStatsOut.of(stats[d.id]),
                )
                for d in goal.active_children
            ],
        )


class GoalCreate(BaseModel):
    title: str = Field(max_length=MAX_TITLE_LEN * 2)
    why: str | None = Field(default=None, max_length=MAX_WHY_LEN * 2)
    # Если указан — создаётся направление внутри этой цели.
    parent_id: int | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LEN * 2)
    why: str | None = Field(default=None, max_length=MAX_WHY_LEN * 2)
