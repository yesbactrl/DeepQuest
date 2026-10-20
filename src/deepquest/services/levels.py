"""Уровни из журнала XP.

- Общий уровень: для уровня n нужно 250 · n · (n − 1) XP (2-й — 500, 5-й — 5 000, 10-й — 22 500).
- Уровень сезона (календарного месяца): 1 + season_xp // 500, первого числа начинается заново.
"""

from dataclasses import dataclass

LEVEL_STEP = 250
SEASON_LEVEL_XP = 500


@dataclass(frozen=True)
class Level:
    level: int
    xp: int
    # С какого XP начался этот уровень и сколько нужно для следующего.
    floor_xp: int
    next_xp: int

    @property
    def progress(self) -> float:
        return (self.xp - self.floor_xp) / (self.next_xp - self.floor_xp)


def xp_for_level(level: int) -> int:
    return LEVEL_STEP * level * (level - 1)


def total_level(xp: int) -> Level:
    xp = max(xp, 0)
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return Level(level=level, xp=xp, floor_xp=xp_for_level(level), next_xp=xp_for_level(level + 1))


def season_level(xp: int) -> Level:
    xp = max(xp, 0)
    level = 1 + xp // SEASON_LEVEL_XP
    return Level(
        level=level,
        xp=xp,
        floor_xp=(level - 1) * SEASON_LEVEL_XP,
        next_xp=level * SEASON_LEVEL_XP,
    )
