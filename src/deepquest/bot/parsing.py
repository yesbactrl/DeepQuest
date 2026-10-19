"""Разбор того, что пользователь пишет боту руками: пояс, длительность, время."""

import os
import re
from datetime import time
from functools import cache
from zoneinfo import available_timezones

CITY_TIMEZONES = {
    "москва": "Europe/Moscow",
    "мск": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "петербург": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "спб": "Europe/Moscow",
    "калининград": "Europe/Kaliningrad",
    "самара": "Europe/Samara",
    "екатеринбург": "Asia/Yekaterinburg",
    "омск": "Asia/Omsk",
    "новосибирск": "Asia/Novosibirsk",
    "красноярск": "Asia/Krasnoyarsk",
    "иркутск": "Asia/Irkutsk",
    "владивосток": "Asia/Vladivostok",
    "киев": "Europe/Kyiv",
    "київ": "Europe/Kyiv",
    "минск": "Europe/Minsk",
    "алматы": "Asia/Almaty",
    "астана": "Asia/Almaty",
    "ташкент": "Asia/Tashkent",
    "бишкек": "Asia/Bishkek",
    "тбилиси": "Asia/Tbilisi",
    "ереван": "Asia/Yerevan",
    "баку": "Asia/Baku",
    "стамбул": "Europe/Istanbul",
    "белград": "Europe/Belgrade",
    "варшава": "Europe/Warsaw",
    "берлин": "Europe/Berlin",
    "лондон": "Europe/London",
    "лиссабон": "Europe/Lisbon",
    "тель-авив": "Asia/Jerusalem",
    "дубай": "Asia/Dubai",
    "бангкок": "Asia/Bangkok",
    "пхукет": "Asia/Bangkok",
    "хошимин": "Asia/Ho_Chi_Minh",
    "сайгон": "Asia/Ho_Chi_Minh",
    "ханой": "Asia/Ho_Chi_Minh",
    "дананг": "Asia/Ho_Chi_Minh",
    "нячанг": "Asia/Ho_Chi_Minh",
    "бали": "Asia/Makassar",
    "денпасар": "Asia/Makassar",
    "нью-йорк": "America/New_York",
}

_OFFSET_RE = re.compile(r"(?:utc|gmt)?\s*([+\-−])\s*(\d{1,2})(?::?00)?")
_CLOCK_RE = re.compile(r"(\d{1,2})(?:[:.\s]?([0-5]\d))?")
_HOURS_MINUTES_RE = re.compile(r"(\d{1,2}):([0-5]\d)")
_UNITS_RE = re.compile(
    r"(?:(?P<hours>\d+(?:\.\d+)?)\s*(?:часов|часа|час|ч|hours|hour|h)\.?)?"
    r"\s*(?:(?P<minutes>\d+)\s*(?:минуты|минут|мин|м|minutes|min|m)\.?)?"
)


@cache
def _timezones_by_lower_name() -> dict[str, str]:
    """Канонические имена поясов: по полному имени и по городу («berlin», «ho chi minh»)."""
    by_name: dict[str, str] = {}
    for name in sorted(available_timezones()):
        if "/" not in name or name.startswith(("Etc/", "SystemV/")):
            continue
        by_name[name.lower()] = name
        city = name.rsplit("/", 1)[1].replace("_", " ").lower()
        by_name.setdefault(city, name)
    return by_name


def resolve_timezone(text: str) -> str | None:
    """«Москва», «Berlin», «Europe/Moscow», «+7», «UTC-3» → имя пояса IANA."""
    value = " ".join(text.strip().lower().split())
    if not value:
        return None
    if value in {"utc", "gmt", "0", "+0", "-0"}:
        return "UTC"
    if value in CITY_TIMEZONES:
        return CITY_TIMEZONES[value]
    if match := _OFFSET_RE.fullmatch(value):
        sign = -1 if match[1] in "-−" else 1
        hours = sign * int(match[2])
        if hours == 0:
            return "UTC"
        if not -12 <= hours <= 14:
            return None
        # В зонах Etc/GMT знак перевёрнут: UTC+7 — это Etc/GMT-7.
        return f"Etc/GMT{-hours:+d}"
    zones = _timezones_by_lower_name()
    return zones.get(value) or zones.get(value.replace("_", " "))


def local_timezone_name() -> str | None:
    """Пояс этого Mac, например «Asia/Ho_Chi_Minh», если его удаётся определить."""
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    _, sep, name = target.partition("zoneinfo/")
    if not sep:
        return None
    return resolve_timezone(name)


def parse_duration_minutes(text: str) -> int | None:
    """«90», «90 мин», «1.5 ч», «1,5», «1ч 30м», «1:30» → минуты.

    Голое целое число — минуты, дробное — часы.
    """
    value = text.strip().lower().replace(",", ".")
    if not value:
        return None
    if match := _HOURS_MINUTES_RE.fullmatch(value):
        return int(match[1]) * 60 + int(match[2])
    if value.isdigit():
        return int(value)
    if re.fullmatch(r"\d+\.\d+", value):
        return round(float(value) * 60)
    match = _UNITS_RE.fullmatch(value)
    if match is None or not (match["hours"] or match["minutes"]):
        return None
    return round(float(match["hours"] or 0) * 60) + int(match["minutes"] or 0)


def parse_clock_time(text: str) -> time | None:
    """«9», «09:30», «9.30», «2130» → time."""
    match = _CLOCK_RE.fullmatch(text.strip())
    if match is None:
        return None
    hour, minute = int(match[1]), int(match[2] or 0)
    if hour > 23:
        return None
    return time(hour, minute)
