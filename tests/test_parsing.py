from datetime import time

import pytest

from deepquest.bot.parsing import parse_clock_time, parse_duration_minutes, resolve_timezone


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Москва", "Europe/Moscow"),
        ("  спб ", "Europe/Moscow"),
        ("Europe/Berlin", "Europe/Berlin"),
        ("europe/berlin", "Europe/Berlin"),
        ("Bangkok", "Asia/Bangkok"),
        ("ho chi minh", "Asia/Ho_Chi_Minh"),
        ("+7", "Etc/GMT-7"),
        ("UTC-3", "Etc/GMT+3"),
        ("utc +5:00", "Etc/GMT-5"),
        ("utc", "UTC"),
        ("+0", "UTC"),
        ("+15", None),
        ("+5:30", None),
        ("Нарния", None),
        ("", None),
    ],
)
def test_resolve_timezone(text: str, expected: str | None) -> None:
    assert resolve_timezone(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("90", 90),
        ("90 мин", 90),
        ("1.5 ч", 90),
        ("1,5", 90),
        ("1ч 30м", 90),
        ("1:30", 90),
        ("2 часа", 120),
        ("2h", 120),
        ("45 min", 45),
        ("полтора", None),
        ("", None),
    ],
)
def test_parse_duration_minutes(text: str, expected: int | None) -> None:
    assert parse_duration_minutes(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("9", time(9)),
        ("09:30", time(9, 30)),
        ("8.15", time(8, 15)),
        ("2130", time(21, 30)),
        ("0", time(0)),
        ("24", None),
        ("9:60", None),
        ("утром", None),
    ],
)
def test_parse_clock_time(text: str, expected: time | None) -> None:
    assert parse_clock_time(text) == expected
