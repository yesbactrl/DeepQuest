"""Сон: отрезки ночного и дневного сна, норма и статистика."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import SleepSession, User
from deepquest.services import sleep
from deepquest.services.sleep import DaySleep, SleepInput
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import (
    SleepDayOut,
    SleepGoalIn,
    SleepIn,
    SleepOut,
    SleepSessionOut,
    SleepStatsOut,
)

router = APIRouter(prefix="/api/sleep", tags=["sleep"])


def _now() -> datetime:
    return datetime.now(UTC)


def _session_out(user: User, item: SleepSession) -> SleepSessionOut:
    return SleepSessionOut(
        id=item.id,
        kind=item.kind,
        start=sleep.to_local(user, item.started_at),
        end=sleep.to_local(user, item.ended_at),
        day=item.day,
        minutes=int((item.ended_at - item.started_at).total_seconds() // 60),
        quality=item.quality,
        note=item.note,
    )


def _day_out(user: User, day: DaySleep) -> SleepDayOut:
    return SleepDayOut(
        day=day.day,
        night_min=day.night_min,
        nap_min=day.nap_min,
        total_min=day.total_min,
        bedtime=day.bedtime,
        wake=day.wake,
        quality=day.quality,
        sessions=[_session_out(user, item) for item in day.sessions],
    )


def _input(body: SleepIn) -> SleepInput:
    # Время приходит местным; если браузер всё же прислал пояс — отбрасываем его.
    return SleepInput(
        kind=body.kind,
        start=body.start.replace(tzinfo=None),
        end=body.end.replace(tzinfo=None),
        quality=body.quality,
        note=body.note,
    )


async def _get(session: AsyncSession, user: User, sleep_id: int) -> SleepSession:
    item = await sleep.get_session(session, user, sleep_id)
    if item is None:
        raise HTTPException(404, "Запись сна не найдена.")
    return item


@router.get("")
async def overview(
    session: SessionDep, user: UserDep, days: Annotated[int, Query(ge=1, le=366)] = 30
) -> SleepOut:
    result = await sleep.overview(session, user, days, _now())
    return SleepOut(
        first=result.first,
        last=result.last,
        goal_min=result.goal_min,
        days=[_day_out(user, day) for day in result.days],
        stats=SleepStatsOut.model_validate(result.stats, from_attributes=True),
    )


@router.post("", status_code=201)
async def add(body: SleepIn, session: SessionDep, user: UserDep) -> SleepSessionOut:
    try:
        item = await sleep.add_session(session, user, _input(body), _now())
    except sleep.SleepError as exc:
        raise HTTPException(422, str(exc)) from None
    return _session_out(user, item)


@router.patch("/goal")
async def set_goal(body: SleepGoalIn, session: SessionDep, user: UserDep) -> dict[str, int]:
    try:
        sleep.set_goal(user, body.goal_min)
    except sleep.SleepError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"goal_min": user.sleep_goal_min}


@router.patch("/{sleep_id}")
async def edit(sleep_id: int, body: SleepIn, session: SessionDep, user: UserDep) -> SleepSessionOut:
    item = await _get(session, user, sleep_id)
    try:
        await sleep.edit_session(session, user, item, _input(body), _now())
    except sleep.SleepError as exc:
        raise HTTPException(422, str(exc)) from None
    return _session_out(user, item)


@router.delete("/{sleep_id}", status_code=204)
async def delete(sleep_id: int, session: SessionDep, user: UserDep) -> Response:
    await session.delete(await _get(session, user, sleep_id))
    return Response(status_code=204)
