"""План по дням: неделя вперёд, «когда-нибудь» и невыполненное с прошлых дней."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from deepquest.db.models import Task
from deepquest.services import plan, stats, tasks
from deepquest.services.days import user_logical_date
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import PlanDayOut, PlanOut, ScheduleIn, TaskOut

router = APIRouter(prefix="/api", tags=["plan"])


@router.get("/plan")
async def get_plan(session: SessionDep, user: UserDep) -> PlanOut:
    now = datetime.now(UTC)
    week = await plan.build_plan(session, user, now)
    everything = [
        *week.unplanned,
        *week.overdue,
        *(task for day in week.days for task in day.tasks),
    ]
    totals = await stats.task_totals(session, everything, now)

    def out(items: list[Task]) -> list[TaskOut]:
        return [TaskOut.of(task, totals[task.id]) for task in items]

    return PlanOut(
        today=week.today,
        norm_min=user.daily_norm_min,
        days=[
            PlanDayOut(
                day=day.day, tasks=out(day.tasks), load_min=day.load_min, load_xp=day.load_xp
            )
            for day in week.days
        ],
        unplanned=out(week.unplanned),
        overdue=out(week.overdue),
        energy_today=week.energy_today,
        drive_today=week.drive_today,
    )


@router.post("/tasks/{task_id}/schedule")
async def schedule(task_id: int, body: ScheduleIn, session: SessionDep, user: UserDep) -> TaskOut:
    task = await tasks.get_task(session, user, task_id)
    if task is None:
        raise HTTPException(404, "Задача не найдена.")
    now = datetime.now(UTC)
    try:
        plan.schedule(task, body.day, user_logical_date(user, now))
    except plan.PlanError:
        raise HTTPException(
            409, "Запланировать можно задачу из бэклога или в работе — на сегодня и позже."
        ) from None
    totals = await stats.task_totals(session, [task], now)
    return TaskOut.of(task, totals[task.id])
