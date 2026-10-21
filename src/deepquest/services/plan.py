"""План по дням: какие задачи на какой день. План — намерение: на XP и стрик он не влияет,
засчитывается по-прежнему сделанное.

Невыполненное в прошлые дни не переезжает на сегодня молча: оно висит отдельно,
«со вчера», и пользователь сам решает, оставить, перенести или вернуть в бэклог.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.db.models import DiaryEntry, Goal, Task, TaskStatus, User
from deepquest.services.days import user_logical_date

# Что можно планировать: сохранённое в бэклог и начатое.
ACTIVE = {TaskStatus.OPEN, TaskStatus.RUNNING, TaskStatus.AWAITING_REPORT}
FINISHED = {TaskStatus.DONE, TaskStatus.REJECTED}
HORIZON_DAYS = 7
# Дальше планировать — уже не план на неделю, а мечты.
MAX_AHEAD_DAYS = 60


class PlanError(ValueError):
    """Задачу нельзя запланировать: черновик, закрыта или день вне разумных пределов."""


def planned_xp(task: Task) -> int:
    """Сколько XP задача даст, если отчёт засчитают целиком и с пруфом."""
    if task.estimate_min is None or task.value_mult is None:
        return 0
    return round(task.estimate_min * task.value_mult)


def schedule(task: Task, day: date | None, today: date) -> None:
    """Поставить задачу на день или вернуть в «когда-нибудь» (`day=None`)."""
    if task.status not in ACTIVE:
        raise PlanError(f"Task {task.id} is {task.status}")
    if day is not None and not today <= day <= today + timedelta(days=MAX_AHEAD_DAYS):
        raise PlanError(f"Day {day} is out of range")
    task.planned_for = day


@dataclass(frozen=True)
class PlanDay:
    day: date
    # Сначала незакрытые, потом сделанные — их видно, но в нагрузку они не идут.
    tasks: list[Task]
    load_min: int
    load_xp: int


@dataclass(frozen=True)
class Plan:
    today: date
    days: list[PlanDay]
    unplanned: list[Task]
    # Запланированное на прошлые дни и не сделанное.
    overdue: list[Task]
    # Средние энергия и желание действовать по дневнику за сегодня — подсказка, сколько брать.
    energy_today: float | None
    drive_today: float | None


def _sort_key(task: Task) -> tuple[bool, float, datetime]:
    return (task.status in FINISHED, -(task.value_mult or 0), task.created_at)


async def build_plan(
    session: AsyncSession, user: User, now: datetime, days: int = HORIZON_DAYS
) -> Plan:
    today = user_logical_date(user, now)
    last = today + timedelta(days=days - 1)
    tasks = list(
        await session.scalars(
            select(Task)
            .where(
                Task.user_id == user.id,
                or_(
                    Task.status.in_(ACTIVE),
                    and_(
                        Task.status.in_(FINISHED),
                        Task.planned_for >= today,
                        Task.planned_for <= last,
                    ),
                ),
            )
            .options(selectinload(Task.goal).selectinload(Goal.parent))
        )
    )
    by_day: dict[date, list[Task]] = {today + timedelta(days=i): [] for i in range(days)}
    unplanned: list[Task] = []
    overdue: list[Task] = []
    for task in sorted(tasks, key=_sort_key):
        if task.planned_for is None:
            unplanned.append(task)
        elif task.planned_for < today:
            overdue.append(task)
        elif task.planned_for in by_day:
            by_day[task.planned_for].append(task)
        # Запланированное дальше горизонта на этой неделе не показываем.

    diary = await session.execute(
        select(DiaryEntry.energy, DiaryEntry.drive).where(
            DiaryEntry.user_id == user.id, DiaryEntry.logical_date == today
        )
    )
    rows = list(diary)

    def average(values: list[int | None]) -> float | None:
        present = [value for value in values if value is not None]
        return round(mean(present), 1) if present else None

    return Plan(
        today=today,
        days=[
            PlanDay(
                day=day,
                tasks=day_tasks,
                load_min=sum(t.estimate_min or 0 for t in day_tasks if t.status in ACTIVE),
                load_xp=sum(planned_xp(t) for t in day_tasks if t.status in ACTIVE),
            )
            for day, day_tasks in by_day.items()
        ],
        unplanned=unplanned,
        overdue=overdue,
        energy_today=average([energy for energy, _ in rows]),
        drive_today=average([drive for _, drive in rows]),
    )
