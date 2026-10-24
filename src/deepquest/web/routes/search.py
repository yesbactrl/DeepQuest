"""Поиск по задачам и дневнику."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from deepquest.services import search, stats
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import DiaryEntryOut, SearchOut, SearchTaskOut, TaskOut

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def run_search(
    session: SessionDep,
    user: UserDep,
    q: Annotated[str, Query(max_length=search.MAX_QUERY_LEN)] = "",
) -> SearchOut:
    result = await search.search(session, user, q)
    totals = await stats.task_totals(session, [hit.task for hit in result.tasks], datetime.now(UTC))
    return SearchOut(
        tasks=[
            SearchTaskOut(
                task=TaskOut.of(hit.task, totals[hit.task.id]), where=hit.where, snippet=hit.snippet
            )
            for hit in result.tasks
        ],
        entries=[DiaryEntryOut.of(entry) for entry in result.entries],
    )
