import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from deepquest.services import devlog


def commit(repo: Path, when: str, message: str, lines: int) -> None:
    (repo / "file.txt").write_text("\n".join(str(i) for i in range(lines)) + "\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True, env=env)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    commit(
        tmp_path,
        "2026-10-20T02:42:00+07:00",
        "M0: каркас бота\n\n- пункт один\n  с продолжением\n- пункт два\n\nCo-Authored-By: X <x@x>",
        300,
    )
    commit(tmp_path, "2026-10-22T10:00:00+07:00", "Задачи: сортировка по XP", 310)
    commit(tmp_path, "2026-10-22T21:00:00+07:00", "Диктовка не теряется: черновики", 600)
    return tmp_path


async def test_devlog_groups_by_day_newest_first(repo: Path) -> None:
    log = await devlog.load(repo)
    assert [d.day for d in log.days] == [date(2026, 10, 22), date(2026, 10, 20)]
    assert (log.commits, log.milestones) == (3, 1)
    fix, polish = log.days[0].commits
    assert (fix.kind, fix.area) == ("fix", "Голос")
    assert (polish.kind, polish.area, polish.insertions) == ("polish", "Задачи", 10)
    [first] = log.days[1].commits
    assert (first.kind, first.milestone, first.title, first.area) == (
        "milestone",
        "M0",
        "Каркас бота",
        "Бот",
    )
    assert first.points == ["пункт один с продолжением", "пункт два"]
    assert first.at.hour == 2 and first.files == 1


async def test_not_a_repo_is_empty(tmp_path: Path) -> None:
    assert (await devlog.load(tmp_path)).days == []


@pytest.mark.parametrize(
    ("subject", "area"),
    [
        ("C1: персонаж — статы", "Персонаж"),
        ("Сон: ночной и дневной", "Сон"),
        ("W3: норма, стрик, уровни", "Норма и стрик"),
        ("Советник: MCP-сервер", "Советник"),
        ("Прочее", None),
    ],
)
def test_area_by_earliest_word(subject: str, area: str | None) -> None:
    assert devlog.area_of(subject) == area
