"""Схемы веб-API: что фронтенд отправляет и получает."""

from datetime import datetime, time

from pydantic import BaseModel, Field

from deepquest.db.models import Goal, GoalStatus, Task, TaskStatus, User, ValidationVerdict
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN, goal_path
from deepquest.services.stats import GoalStats, TaskTotals


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


# Задачи


class TaskOut(BaseModel):
    id: int
    title: str
    expected_result: str | None
    status: TaskStatus
    goal_id: int | None
    goal_path: str | None
    estimate_min: int | None
    value_mult: float | None
    mult_reason: str | None
    source_text: str
    clarify_question: str | None
    created_at: datetime
    updated_at: datetime
    spent_min: int
    xp: int
    running_since: datetime | None

    @classmethod
    def of(cls, task: Task, totals: TaskTotals) -> TaskOut:
        return cls(
            id=task.id,
            title=task.title,
            expected_result=task.expected_result,
            status=task.status,
            goal_id=task.goal_id,
            goal_path=goal_path(task.goal) if task.goal else None,
            estimate_min=task.estimate_min,
            value_mult=task.value_mult,
            mult_reason=task.mult_reason,
            source_text=task.source_text,
            clarify_question=task.clarify_question,
            created_at=task.created_at,
            updated_at=task.updated_at,
            spent_min=totals.minutes,
            xp=totals.xp,
            running_since=totals.running_since,
        )


class ProofOut(BaseModel):
    index: int
    kind: str
    name: str | None
    url: str | None
    is_image: bool


class ReportOut(BaseModel):
    text: str
    honor_mode: bool
    created_at: datetime
    proofs: list[ProofOut]


class ValidationOut(BaseModel):
    verdict: ValidationVerdict
    reason: str
    comment: str
    is_dispute: bool
    dispute_text: str | None
    created_at: datetime


class XpBreakdownOut(BaseModel):
    actual_min: int
    estimate_min: int
    counted_min: int
    capped: bool
    value_mult: float
    verdict: str
    validation_mult: float
    honor_mode: bool
    proof_mult: float
    amount: int


class TaskDetailOut(TaskOut):
    report: ReportOut | None
    validation: ValidationOut | None
    breakdown: XpBreakdownOut | None
    can_dispute: bool


class PlanIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ClarifyIn(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class ReviseIn(BaseModel):
    # Пусто — оценить заново с нуля.
    correction: str | None = Field(default=None, max_length=4000)


class DisputeIn(BaseModel):
    argument: str = Field(min_length=1, max_length=4000)


class TaskEdit(BaseModel):
    title: str | None = None
    expected_result: str | None = None
    goal_id: int | None = None
    estimate_min: int | None = None
    value_mult: float | None = None
    mult_reason: str | None = None


class PlanOutcomeOut(BaseModel):
    tasks: list[TaskOut]
    question: str | None
    agent_failed: bool


class ReviseOut(BaseModel):
    task: TaskDetailOut
    agent_failed: bool


class StartOut(BaseModel):
    task: TaskDetailOut
    paused_task_id: int | None


class CheckOut(BaseModel):
    task: TaskDetailOut
    agent_failed: bool
    xp_delta: int
    total_xp: int


class TimerOut(BaseModel):
    task_id: int
    title: str
    goal_path: str | None
    started_at: datetime
    # Сколько минут ушло на задачу до текущего запуска: остальное фронтенд досчитывает сам.
    before_min: int
