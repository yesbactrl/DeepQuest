"""Сводка для дашборда и /stats: уровень, сезон, норма сегодня и стрик."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import User
from deepquest.services import xp
from deepquest.services.days import season_of
from deepquest.services.levels import Level, level_of
from deepquest.services.streak import StreakInfo, streak_info


@dataclass(frozen=True)
class Summary:
    total: Level
    season: str  # «2026-10»
    season_level: Level
    streak: StreakInfo


async def build_summary(session: AsyncSession, user: User, now: datetime) -> Summary:
    streak = await streak_info(session, user, now)
    season = season_of(streak.today)
    return Summary(
        total=level_of(await xp.total_xp(session, user)),
        season=season,
        season_level=level_of(await xp.season_xp(session, user, season)),
        streak=streak,
    )
