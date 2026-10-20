"""Персонаж: уровень, сезон, стрик и статы — цели с уровнями, скиллы — направления."""

from datetime import UTC, datetime

from fastapi import APIRouter

from deepquest.services.character import WEAK_STAT_MULT, build_character
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import CharacterOut

router = APIRouter(prefix="/api", tags=["character"])


@router.get("/character")
async def character(session: SessionDep, user: UserDep) -> CharacterOut:
    return CharacterOut.of(await build_character(session, user, datetime.now(UTC)), WEAK_STAT_MULT)
