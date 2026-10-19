"""Логический день и сезон пользователя.

День заканчивается не в полночь, а в `day_boundary_hour` по поясу пользователя:
работа в 01:30 при границе 04:00 относится к «вчера».
"""

from datetime import date, datetime, timedelta
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
