from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import User

DEFAULT_TZ = "UTC"
DEFAULT_DAY_BOUNDARY_HOUR = 4
DEFAULT_DAILY_NORM_MIN = 60
DEFAULT_MORNING_AT = time(9, 0)
DEFAULT_EVENING_AT = time(21, 0)
DEFAULT_FREEZES_PER_WEEK = 2

MIN_DAILY_NORM_MIN = 10
MAX_DAILY_NORM_MIN = 12 * 60


async def get_or_create_user(session: AsyncSession, telegram_id: int) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        user = User(
            telegram_id=telegram_id,
            tz=DEFAULT_TZ,
            day_boundary_hour=DEFAULT_DAY_BOUNDARY_HOUR,
            daily_norm_min=DEFAULT_DAILY_NORM_MIN,
            morning_at=DEFAULT_MORNING_AT,
            evening_at=DEFAULT_EVENING_AT,
            freezes_per_week=DEFAULT_FREEZES_PER_WEEK,
        )
        session.add(user)
        await session.flush()
    return user


def set_timezone(user: User, tz: str) -> None:
    ZoneInfo(tz)  # ZoneInfoNotFoundError, если такого пояса нет
    user.tz = tz


def set_daily_norm(user: User, minutes: int) -> None:
    if not MIN_DAILY_NORM_MIN <= minutes <= MAX_DAILY_NORM_MIN:
        raise ValueError(f"Daily norm out of range: {minutes} min")
    user.daily_norm_min = minutes


def set_morning_at(user: User, at: time) -> None:
    user.morning_at = at


def set_evening_at(user: User, at: time) -> None:
    if at <= user.morning_at:
        raise ValueError(f"Evening {at} must be after morning {user.morning_at}")
    user.evening_at = at


def finish_onboarding(user: User, now: datetime) -> None:
    # Повторная настройка через /settings не сдвигает дату первого онбординга.
    if user.onboarded_at is None:
        user.onboarded_at = now
