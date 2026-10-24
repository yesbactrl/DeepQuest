"""Итоги недели или месяца и их разбор агентом."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from deepquest.services import review
from deepquest.services.review import PeriodKind
from deepquest.web.deps import ContextDep, SessionDep, UserDep
from deepquest.web.schemas import ReviewAnalyzeOut, ReviewOut

router = APIRouter(prefix="/api/review", tags=["review"])

# offset — сколько периодов назад: 0 — текущий.
Offset = Annotated[int, Query(ge=0, le=520)]


async def _build(
    session: SessionDep, user: UserDep, kind: PeriodKind, offset: int
) -> review.PeriodReview:
    return await review.build_review(session, user, kind, offset, datetime.now(UTC))


@router.get("")
async def get_review(
    session: SessionDep, user: UserDep, kind: PeriodKind = PeriodKind.WEEK, offset: Offset = 0
) -> ReviewOut:
    return ReviewOut.of(await _build(session, user, kind, offset))


@router.post("/analyze")
async def analyze_review(
    session: SessionDep,
    user: UserDep,
    context: ContextDep,
    kind: PeriodKind = PeriodKind.WEEK,
    offset: Offset = 0,
) -> ReviewAnalyzeOut:
    period_review = await _build(session, user, kind, offset)
    ok = await review.analyze(session, context.agent, user, period_review, datetime.now(UTC))
    return ReviewAnalyzeOut(review=ReviewOut.of(period_review), agent_failed=not ok)
