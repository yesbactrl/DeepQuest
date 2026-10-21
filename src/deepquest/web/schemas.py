"""Схемы веб-API: что фронтенд отправляет и получает."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field

from deepquest.db.models import Goal, GoalStatus, Task, TaskStatus, User, ValidationVerdict, XpKind
from deepquest.services.character import Award, Character, Stat
from deepquest.services.charts import ChartConfig, ChartData
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN, PALETTE, goal_path
from deepquest.services.levels import Level
from deepquest.services.stats import GoalStats, TaskTotals
from deepquest.services.summary import Summary


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
    growth_only: bool
    created_at: datetime
    stats: GoalStatsOut


class GoalOut(BaseModel):
    id: int
    title: str
    why: str | None
    status: GoalStatus
    color: str
    icon: str | None
    growth_only: bool
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
            color=goal.color or PALETTE[0],
            icon=goal.icon,
            growth_only=goal.growth_only,
            created_at=goal.created_at,
            stats=GoalStatsOut.of(stats[goal.id]),
            directions=[
                DirectionOut(
                    id=d.id,
                    title=d.title,
                    why=d.why,
                    growth_only=d.growth_only,
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


GoalColor = Literal["blue", "orange", "green", "amber", "pink", "forest", "violet", "red"]


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LEN * 2)
    why: str | None = Field(default=None, max_length=MAX_WHY_LEN * 2)
    # Цвет и иконка — только у цели: направления берут их у неё. Пустая иконка — по умолчанию.
    color: GoalColor | None = None
    icon: str | None = Field(default=None, pattern=r"^[a-z0-9-]{0,32}$")
    growth_only: bool | None = None


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
    weak_mult: float


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


class TimeIn(BaseModel):
    # Сутки — с запасом: больше двух оценок в XP всё равно не засчитывается.
    spent_min: int = Field(ge=1, le=24 * 60)


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
    # Куда пошёл XP, кроме общего уровня: стат (цель) и скилл (направление) задачи.
    stat: str | None = None
    skill: str | None = None
    weak_mult: float = 1.0


class TimerOut(BaseModel):
    task_id: int
    title: str
    goal_path: str | None
    started_at: datetime
    # Сколько минут ушло на задачу до текущего запуска: остальное фронтенд досчитывает сам.
    before_min: int


# Сводка и графики


class LevelOut(BaseModel):
    level: int
    xp: int
    floor_xp: int
    next_xp: int
    progress: float

    @classmethod
    def of(cls, level: Level) -> LevelOut:
        return cls(
            level=level.level,
            xp=level.xp,
            floor_xp=level.floor_xp,
            next_xp=level.next_xp,
            progress=level.progress,
        )


class DayMarkOut(BaseModel):
    day: date
    status: str
    focus_min: int
    norm_min: int


class StreakOut(BaseModel):
    current: int
    best: int
    today: date
    today_focus_min: int
    norm_min: int
    today_met: bool
    freezes_left: int
    freezes_per_week: int
    recent: list[DayMarkOut]


class SummaryOut(BaseModel):
    total: LevelOut
    season: str
    season_level: LevelOut
    streak: StreakOut

    @classmethod
    def of(cls, summary: Summary) -> SummaryOut:
        streak = summary.streak
        return cls(
            total=LevelOut.of(summary.total),
            season=summary.season,
            season_level=LevelOut.of(summary.season_level),
            streak=StreakOut(
                current=streak.current,
                best=streak.best,
                today=streak.today,
                today_focus_min=streak.today_focus_min,
                norm_min=streak.norm_min,
                today_met=streak.today_met,
                freezes_left=streak.freezes_left,
                freezes_per_week=streak.freezes_per_week,
                recent=[
                    DayMarkOut(
                        day=m.day, status=m.status, focus_min=m.focus_min, norm_min=m.norm_min
                    )
                    for m in streak.recent
                ],
            ),
        )


class SeriesOut(BaseModel):
    key: str
    name: str
    values: list[float]
    slot: int


class ChartDataOut(BaseModel):
    buckets: list[str]
    labels: list[str]
    series: list[SeriesOut]
    norm_min: int | None

    @classmethod
    def of(cls, data: ChartData) -> ChartDataOut:
        return cls(
            buckets=data.buckets,
            labels=data.labels,
            series=[
                SeriesOut(key=s.key, name=s.name, values=s.values, slot=s.slot) for s in data.series
            ],
            norm_min=data.norm_min,
        )


class WidgetOut(BaseModel):
    id: int
    position: int
    config: ChartConfig


# Голос


class VoiceStatusOut(BaseModel):
    enabled: bool


class TranscriptOut(BaseModel):
    text: str


# Персонаж


class SkillOut(BaseModel):
    id: int
    title: str
    level: LevelOut


class StatOut(BaseModel):
    id: int
    title: str
    color: str
    icon: str | None
    growth_only: bool
    level: LevelOut
    season_xp: int
    weakest: bool
    skills: list[SkillOut]

    @classmethod
    def of(cls, stat: Stat) -> StatOut:
        goal = stat.goal
        return cls(
            id=goal.id,
            title=goal.title,
            color=goal.color or PALETTE[0],
            icon=goal.icon,
            growth_only=goal.growth_only,
            level=LevelOut.of(stat.level),
            season_xp=stat.season_xp,
            weakest=stat.weakest,
            skills=[
                SkillOut(id=s.goal.id, title=s.goal.title, level=LevelOut.of(s.level))
                for s in stat.skills
            ],
        )


class AwardOut(BaseModel):
    kind: XpKind
    amount: int
    task_title: str | None
    stat: str | None
    skill: str | None
    created_at: datetime

    @classmethod
    def of(cls, award: Award) -> AwardOut:
        return cls(
            kind=award.kind,
            amount=award.amount,
            task_title=award.task_title,
            stat=award.stat,
            skill=award.skill,
            created_at=award.created_at,
        )


class LevelStepOut(BaseModel):
    level: int
    cost: int
    total: int


class XpRulesOut(BaseModel):
    """Из чего складывается XP за задачу — те же числа, что в services/xp.py."""

    xp_per_minute: int
    cap_factor: int
    value_mults: list[float]
    validation_mults: dict[str, float]
    honor_mode_mult: float
    weak_stat_mult: float


class LevelsOut(BaseModel):
    steps: list[LevelStepOut]
    rules: XpRulesOut
    daily_norm_min: int


class CharacterOut(BaseModel):
    summary: SummaryOut
    stats: list[StatOut]
    last_award: AwardOut | None
    weak_stat_mult: float

    @classmethod
    def of(cls, character: Character, weak_stat_mult: float) -> CharacterOut:
        return cls(
            summary=SummaryOut.of(character.summary),
            stats=[StatOut.of(stat) for stat in character.stats],
            last_award=AwardOut.of(character.last_award) if character.last_award else None,
            weak_stat_mult=weak_stat_mult,
        )
