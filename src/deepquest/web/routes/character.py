"""Персонаж: уровень, сезон, стрик и статы — цели с уровнями, скиллы — направления."""

from datetime import UTC, datetime

from fastapi import APIRouter

from deepquest.agent.schemas import VALUE_MULTIPLIERS
from deepquest.services import xp
from deepquest.services.character import WEAK_STAT_MULT, build_character
from deepquest.services.levels import scale
from deepquest.web.deps import SessionDep, UserDep
from deepquest.web.schemas import CharacterOut, LevelsOut, LevelStepOut, XpRulesOut

# Сколько уровней показывать на шкале: дальше — годы работы.
SCALE_LEVELS = 30

router = APIRouter(prefix="/api", tags=["character"])


@router.get("/character")
async def character(session: SessionDep, user: UserDep) -> CharacterOut:
    return CharacterOut.of(await build_character(session, user, datetime.now(UTC)), WEAK_STAT_MULT)


@router.get("/levels")
async def levels(user: UserDep) -> LevelsOut:
    return LevelsOut(
        steps=[
            LevelStepOut(level=s.level, cost=s.cost, total=s.total) for s in scale(SCALE_LEVELS)
        ],
        rules=XpRulesOut(
            xp_per_minute=xp.XP_PER_MINUTE,
            value_mults=list(VALUE_MULTIPLIERS),
            validation_mults={verdict.value: mult for verdict, mult in xp.VALIDATION_MULTS.items()},
            no_proof_mult=xp.NO_PROOF_MULT,
            proof_mult=xp.PROOF_MULT,
            weak_stat_mult=WEAK_STAT_MULT,
            diary_entry_xp=xp.DIARY_ENTRY_XP,
            sleep_night_xp=xp.SLEEP_NIGHT_XP,
            sleep_nap_xp=xp.SLEEP_NAP_XP,
        ),
        daily_norm_min=user.daily_norm_min,
    )
