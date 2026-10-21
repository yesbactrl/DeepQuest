"""Уровни из журнала XP. Одна формула на всё: общий уровень, сезон, статы и скиллы.

Переход с уровня L на L + 1 стоит round(100 · L^1.4) XP: первые уровни даются быстро,
дальше медленнее. Чтобы взять 2-й уровень, нужно 100 XP, 5-й — 1 526, 10-й — 9 237.
Уровни нигде не хранятся: поменяй формулу — всё пересчитается само.
"""

from dataclasses import dataclass

BASE_XP = 100
GROWTH = 1.4


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


def xp_to_next(level: int) -> int:
    """Сколько XP стоит переход с `level` на следующий уровень."""
    return round(BASE_XP * level**GROWTH)


@dataclass(frozen=True)
class Step:
    level: int
    # Сколько XP стоит взять этот уровень с предыдущего и сколько нужно всего с нуля.
    cost: int
    total: int


def scale(max_level: int) -> list[Step]:
    """Шкала уровней с 1-го по `max_level`: для экрана «Уровни» и проверки баланса."""
    steps, total = [Step(level=1, cost=0, total=0)], 0
    for level in range(2, max_level + 1):
        cost = xp_to_next(level - 1)
        total += cost
        steps.append(Step(level=level, cost=cost, total=total))
    return steps


def level_of(xp: int) -> Level:
    xp = max(xp, 0)
    level, floor = 1, 0
    while floor + xp_to_next(level) <= xp:
        floor += xp_to_next(level)
        level += 1
    return Level(level=level, xp=xp, floor_xp=floor, next_xp=floor + xp_to_next(level))
