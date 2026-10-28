"""Схемы веб-API: что фронтенд отправляет и получает."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from deepquest.db.models import (
    DayStatus,
    DiaryEntry,
    DiaryStatus,
    Goal,
    GoalStatus,
    SleepKind,
    Task,
    TaskStatus,
    User,
    ValidationVerdict,
    XpKind,
)
from deepquest.services.character import Award, Character, Stat
from deepquest.services.charts import ChartConfig, ChartData
from deepquest.services.diary import Day, backdated
from deepquest.services.goals import MAX_TITLE_LEN, MAX_WHY_LEN, PALETTE, goal_path
from deepquest.services.levels import Level
from deepquest.services.review import PeriodKind, PeriodReview
from deepquest.services.stats import GoalStats, TaskTotals
from deepquest.services.summary import Summary
from deepquest.services.validation import MAX_CREDITED_MIN, MIN_CREDITED_MIN


class MeOut(BaseModel):
    tz: str
    daily_norm_min: int
    morning_at: time
    evening_at: time
    day_boundary_hour: int
    onboarded: bool
    streak_paused: bool

    @classmethod
    def of(cls, user: User) -> MeOut:
        return cls(
            tz=user.tz,
            daily_norm_min=user.daily_norm_min,
            morning_at=user.morning_at,
            evening_at=user.evening_at,
            day_boundary_hour=user.day_boundary_hour,
            onboarded=user.onboarded_at is not None,
            streak_paused=user.streak_paused_at is not None,
        )


class MeUpdate(BaseModel):
    # False — поставить норму и стрик на паузу, True — снова считать.
    streak_enabled: bool | None = None


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
    # День в плане; пусто — «когда-нибудь».
    planned_for: date | None

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
            planned_for=task.planned_for,
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
    # Засчитано самим пользователем, без агента.
    self_check: bool
    created_at: datetime


class XpBreakdownOut(BaseModel):
    actual_min: int
    estimate_min: int
    counted_min: int
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


class EstimateIn(BaseModel):
    # Задним числом — до суток: задача могла растянуться дольше оценки агента.
    estimate_min: int = Field(ge=MIN_CREDITED_MIN, le=MAX_CREDITED_MIN)


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
    # Норма и стрик на паузе: интерфейс их прячет.
    paused: bool


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
                paused=streak.paused,
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
    id: int
    text: str
    created_at: datetime


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
    value_mults: list[float]
    validation_mults: dict[str, float]
    # Без пруфа и со скрином или ссылкой.
    no_proof_mult: float
    proof_mult: float
    weak_stat_mult: float
    # Не за задачи: запись в дневник, сон за день — ночной и дневной.
    diary_entry_xp: int
    sleep_night_xp: int
    sleep_nap_xp: int


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


# Дневник


class DiarySphereOut(BaseModel):
    goal_id: int
    score: int | None
    good: str | None
    bad: str | None


class DiaryEntryOut(BaseModel):
    id: int
    text: str
    created_at: datetime
    logical_date: date
    part_of_day: str
    mood: int | None
    energy: int | None
    drive: int | None
    emotions: list[str]
    factors: list[str]
    summary: str | None
    status: DiaryStatus
    edited: bool
    # Сферы — цели, о которых запись что-то говорит. Название и цвет фронтенд берёт из целей.
    spheres: list[DiarySphereOut]
    # Запись про другой день, чем написана: задним числом или перенесена.
    backdated: bool

    @classmethod
    def of(cls, entry: DiaryEntry, user: User) -> DiaryEntryOut:
        return cls(
            backdated=backdated(user, entry),
            id=entry.id,
            text=entry.text,
            created_at=entry.created_at,
            logical_date=entry.logical_date,
            part_of_day=entry.part_of_day,
            mood=entry.mood,
            energy=entry.energy,
            drive=entry.drive,
            emotions=entry.emotions,
            factors=entry.factors,
            summary=entry.summary,
            status=entry.status,
            edited=entry.edited,
            spheres=[
                DiarySphereOut(goal_id=s.goal_id, score=s.score, good=s.good, bad=s.bad)
                for s in entry.spheres
            ],
        )


class DiaryDayOut(BaseModel):
    day: date
    mood: float | None
    energy: float | None
    drive: float | None
    focus_min: int
    xp: int
    entries: list[DiaryEntryOut]

    @classmethod
    def of(cls, day: Day, user: User) -> DiaryDayOut:
        return cls(
            day=day.day,
            mood=day.mood,
            energy=day.energy,
            drive=day.drive,
            focus_min=day.focus_min,
            xp=day.xp,
            entries=[DiaryEntryOut.of(entry, user) for entry in day.entries],
        )


class DiaryOut(BaseModel):
    days: list[DiaryDayOut]
    norm_min: int


class DiaryIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # False — не отдавать запись агенту: оценки ставятся вручную.
    analyze: bool = True
    # Сферы, которые пользователь отметил сам: про них агент напишет обязательно.
    goal_ids: list[int] = Field(default_factory=list, max_length=20)
    # Логический день записи, если не сегодня: задним числом, до 30 дней назад.
    day: date | None = None


class DiarySphereIn(BaseModel):
    goal_id: int
    # 1–10; 0 или пусто — без оценки.
    score: int | None = Field(default=None, ge=0, le=10)
    good: str | None = Field(default=None, max_length=300)
    bad: str | None = Field(default=None, max_length=300)


class DiaryEditIn(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    # 1–10; 0 — убрать оценку («не знаю»).
    mood: int | None = Field(default=None, ge=0, le=10)
    energy: int | None = Field(default=None, ge=0, le=10)
    drive: int | None = Field(default=None, ge=0, le=10)
    emotions: list[str] | None = Field(default=None, max_length=10)
    factors: list[str] | None = Field(default=None, max_length=10)
    summary: str | None = Field(default=None, max_length=200)
    # Сферы целиком; пусто — не менять.
    spheres: list[DiarySphereIn] | None = Field(default=None, max_length=20)
    # Перенести запись на другой день (XP переезжает вместе с ней).
    day: date | None = None


class SearchTaskOut(BaseModel):
    task: TaskOut
    # Где нашлось и кусок текста вокруг; пусто — нашлось в названии.
    where: str | None
    snippet: str | None


class SearchOut(BaseModel):
    tasks: list[SearchTaskOut]
    entries: list[DiaryEntryOut]


class DiaryEntryResult(BaseModel):
    entry: DiaryEntryOut
    agent_failed: bool
    # XP за саму запись; 0 — при повторном разборе.
    xp: int = 0


# План


class ScheduleIn(BaseModel):
    # null — вернуть в «когда-нибудь».
    day: date | None


class PlanDayOut(BaseModel):
    day: date
    tasks: list[TaskOut]
    # Нагрузка — только незакрытые задачи: сумма оценок и XP, если всё засчитают.
    load_min: int
    load_xp: int


class PlanOut(BaseModel):
    today: date
    # None — норма на паузе: нагрузку дня не с чем сравнивать.
    norm_min: int | None
    days: list[PlanDayOut]
    unplanned: list[TaskOut]
    overdue: list[TaskOut]
    energy_today: float | None
    drive_today: float | None


# Итоги периода


class _FromAttrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TotalsOut(_FromAttrs):
    xp: int
    minutes: int
    done_tasks: int
    entries: int
    norm_met: int
    norm_days: int


class StateOut(_FromAttrs):
    mood: float | None
    energy: float | None
    drive: float | None


class SphereReviewOut(_FromAttrs):
    goal_id: int
    title: str
    xp: int
    prev_xp: int
    minutes: int
    done_tasks: int
    score: float | None
    prev_score: float | None
    mentions: int
    good: list[str]
    bad: list[str]


class DayPointOut(_FromAttrs):
    day: date
    state: float | None
    focus_min: int
    xp: int
    status: DayStatus | None
    sleep_min: int | None


class DayGroupOut(_FromAttrs):
    days: int
    focus_min: float | None
    xp: float | None
    factors: list[tuple[str, int]]


class TopTaskOut(_FromAttrs):
    id: int
    title: str
    goal_id: int | None
    xp: int


class ReviewAnalysisOut(_FromAttrs):
    summary: str
    wins: list[str]
    struggles: list[str]
    patterns: list[str]
    next_steps: list[str]


class ReviewOut(BaseModel):
    kind: PeriodKind
    first: date
    last: date
    end: date
    label: str
    in_progress: bool
    totals: TotalsOut
    prev_totals: TotalsOut
    state: StateOut
    prev_state: StateOut
    spheres: list[SphereReviewOut]
    days: list[DayPointOut]
    bad_days: DayGroupOut
    good_days: DayGroupOut
    emotions: list[tuple[str, int]]
    factors: list[tuple[str, int]]
    top_tasks: list[TopTaskOut]
    sleep: SleepStatsOut
    prev_sleep: SleepStatsOut
    sleep_goal_min: int
    analysis: ReviewAnalysisOut | None
    analyzed_at: datetime | None

    @classmethod
    def of(cls, review: PeriodReview) -> ReviewOut:
        return cls.model_validate(
            {
                **{
                    name: getattr(review, name)
                    for name in (
                        "end", "totals", "prev_totals", "state", "prev_state", "spheres",
                        "days", "bad_days", "good_days", "emotions", "factors", "top_tasks",
                        "analysis", "analyzed_at", "in_progress", "sleep", "prev_sleep",
                        "sleep_goal_min",
                    )
                },
                "kind": review.period.kind,
                "first": review.period.first,
                "last": review.period.last,
                "label": review.period.label,
            },
            from_attributes=True,
        )  # fmt: skip


class ReviewAnalyzeOut(BaseModel):
    review: ReviewOut
    agent_failed: bool


# Сон


class SleepIn(BaseModel):
    kind: SleepKind = SleepKind.NIGHT
    # Местное время пользователя без пояса: «2026-10-24T07:00».
    start: datetime
    end: datetime
    quality: int | None = Field(default=None, ge=1, le=10)
    note: str | None = Field(default=None, max_length=300)


class SleepGoalIn(BaseModel):
    goal_min: int = Field(ge=240, le=720)


class SleepSessionOut(BaseModel):
    id: int
    kind: SleepKind
    # Местное время пользователя без пояса.
    start: datetime
    end: datetime
    day: date
    minutes: int
    quality: int | None
    note: str | None
    # Сколько XP за сон принесла эта правка (за день: +10 ночь, +5 дневной).
    xp_delta: int = 0


class SleepDayOut(BaseModel):
    day: date
    night_min: int
    nap_min: int
    total_min: int
    bedtime: datetime | None
    wake: datetime | None
    quality: float | None
    sessions: list[SleepSessionOut]


class SleepGroupOut(_FromAttrs):
    days: int
    state: float | None
    focus_min: float | None


class SleepStatsOut(_FromAttrs):
    days: int
    avg_total_min: int | None
    avg_night_min: int | None
    avg_nap_min: int | None
    avg_bedtime: int | None
    avg_wake: int | None
    bedtime_spread_min: int | None
    goal_met: int
    debt_min: int
    avg_quality: float | None
    short: SleepGroupOut
    enough: SleepGroupOut


class SleepOut(BaseModel):
    first: date
    last: date
    goal_min: int
    days: list[SleepDayOut]
    stats: SleepStatsOut


# Советник


class AdvisorMessageOut(_FromAttrs):
    id: int
    role: str
    text: str
    tools: list[str]
    error: str | None
    latency_ms: int | None
    created_at: datetime


class AdvisorChatOut(_FromAttrs):
    id: int
    title: str
    model: str
    created_at: datetime
    updated_at: datetime
    # Ответ сейчас пишется: веб подписывается на поток.
    running: bool = False


class AdvisorChatDetailOut(AdvisorChatOut):
    messages: list[AdvisorMessageOut]


class AdvisorChatIn(BaseModel):
    model: str | None = None


class AdvisorChatEdit(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    model: str | None = None


class AdvisorMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class AdvisorNoteOut(_FromAttrs):
    id: int
    text: str
    created_at: datetime


class AdvisorNoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class AdvisorInfoOut(BaseModel):
    # Советника нет, если не нашёлся Claude Code.
    available: bool
    models: dict[str, str]
    default_model: str


# История разработки


class DevCommitOut(_FromAttrs):
    hash: str
    short: str
    at: datetime
    subject: str
    title: str
    milestone: str | None
    area: str | None
    kind: str
    points: list[str]
    files: int
    insertions: int
    deletions: int


class DevDayOut(_FromAttrs):
    day: date
    insertions: int
    deletions: int
    commits: list[DevCommitOut]


class DevlogOut(_FromAttrs):
    commits: int
    milestones: int
    insertions: int
    days: list[DevDayOut]
