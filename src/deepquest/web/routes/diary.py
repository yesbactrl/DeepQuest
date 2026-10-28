"""Дневник: записи о состоянии, разбор агентом и ручная правка оценок."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import DiaryEntry, User
from deepquest.services import diary
from deepquest.services.diary import EntryEdit, EntryOutcome, SphereEdit
from deepquest.web.deps import ContextDep, SessionDep, UserDep
from deepquest.web.schemas import (
    DiaryDayOut,
    DiaryEditIn,
    DiaryEntryOut,
    DiaryEntryResult,
    DiaryIn,
    DiaryOut,
)

router = APIRouter(prefix="/api/diary", tags=["diary"])

ENTRY_NOT_FOUND = "Запись не найдена."


def _now() -> datetime:
    return datetime.now(UTC)


async def _entry(session: AsyncSession, user: User, entry_id: int) -> DiaryEntry:
    entry = await diary.get_entry(session, user, entry_id)
    if entry is None:
        raise HTTPException(404, ENTRY_NOT_FOUND)
    return entry


def _result(outcome: EntryOutcome, user: User) -> DiaryEntryResult:
    return DiaryEntryResult(
        entry=DiaryEntryOut.of(outcome.entry, user),
        agent_failed=outcome.agent_failed,
        xp=outcome.xp,
    )


@router.get("")
async def list_diary(
    session: SessionDep,
    user: UserDep,
    days: Annotated[int, Query(ge=1, le=366)] = 60,
    goal_id: int | None = None,
) -> DiaryOut:
    items = await diary.list_days(session, user, _now(), days, goal_id)
    return DiaryOut(days=[DiaryDayOut.of(day, user) for day in items], norm_min=user.daily_norm_min)


@router.post("", status_code=201)
async def add_entry(
    body: DiaryIn, session: SessionDep, user: UserDep, context: ContextDep
) -> DiaryEntryResult:
    try:
        outcome = await diary.add_entry(
            session,
            context.agent,
            user,
            body.text,
            _now(),
            analyze=body.analyze,
            goal_ids=body.goal_ids,
            day=body.day,
        )
    except diary.DiaryError as exc:
        raise HTTPException(422, str(exc)) from None
    return _result(outcome, user)


@router.patch("/{entry_id}")
async def edit_entry(
    entry_id: int, body: DiaryEditIn, session: SessionDep, user: UserDep
) -> DiaryEntryOut:
    entry = await _entry(session, user, entry_id)
    if body.day is not None:
        try:
            await diary.move_entry(session, user, entry, body.day, _now())
        except diary.DiaryError as exc:
            raise HTTPException(422, str(exc)) from None
    changes = body.model_dump(exclude={"spheres", "day"})
    spheres = (
        [SphereEdit(s.goal_id, s.score, s.good, s.bad) for s in body.spheres]
        if body.spheres is not None
        else None
    )
    await diary.edit_entry(session, user, entry, EntryEdit(**changes, spheres=spheres))
    await session.flush()
    return DiaryEntryOut.of(entry, user)


@router.post("/{entry_id}/analyze")
async def analyze_entry(
    entry_id: int, session: SessionDep, user: UserDep, context: ContextDep
) -> DiaryEntryResult:
    entry = await _entry(session, user, entry_id)
    return _result(await diary.reanalyze(session, context.agent, user, entry), user)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(entry_id: int, session: SessionDep, user: UserDep) -> Response:
    await diary.delete_entry(session, user, await _entry(session, user, entry_id), _now())
    return Response(status_code=204)
