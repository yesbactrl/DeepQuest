"""Логический день и сезон пользователя.

День заканчивается не в полночь, а в `day_boundary_hour` по поясу пользователя:
работа в 01:30 при границе 04:00 относится к «вчера».
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from deepquest.db.models import User


def logical_date(moment: datetime, tz: str, boundary_hour: int) -> date:
    local = moment.astimezone(ZoneInfo(tz))
    return (local - timedelta(hours=boundary_hour)).date()


def user_logical_date(user: User, moment: datetime) -> date:
    return logical_date(moment, user.tz, user.day_boundary_hour)


def season_of(day: date) -> str:
    """Сезон — календарный месяц логического дня: «2026-10»."""
    return f"{day:%Y-%m}"


def local_time(user: User, moment: datetime) -> datetime:
    return moment.astimezone(ZoneInfo(user.tz))


def day_start(day: date, tz: str, boundary_hour: int) -> datetime:
    """Момент (UTC), когда начинается логический день `day`."""
    local = datetime.combine(day, time(boundary_hour), tzinfo=ZoneInfo(tz))
    return local.astimezone(UTC)


def user_day_bounds(user: User, day: date) -> tuple[datetime, datetime]:
    start = day_start(day, user.tz, user.day_boundary_hour)
    end = day_start(day + timedelta(days=1), user.tz, user.day_boundary_hour)
    return start, end


def split_by_day(user: User, start: datetime, end: datetime) -> list[tuple[date, float]]:
    """Режет отрезок времени по границам логических дней: [(день, секунд), …]."""
    pieces = []
    day = user_logical_date(user, start)
    while start < end:
        _, day_end = user_day_bounds(user, day)
        piece_end = min(end, day_end)
        pieces.append((day, (piece_end - start).total_seconds()))
        start = piece_end
        day += timedelta(days=1)
    return pieces
