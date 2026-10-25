"""История разработки DeepQuest — из git, по дням.

Читаем `git log` репозитория на каждый запрос: коммитов сотни, это десятки миллисекунд,
зато страница обновляется сама с каждым коммитом. Из коммита берём заголовок, пункты
описания (строки «- …»), время и сколько строк изменено. Раздел приложения угадывается по
словам заголовка, а вехи плана («M0:», «W2:», «D1.5:») выделяются отдельно.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

RECORD = "\x1e"
FIELD = "\x1f"
END = "\x1d"
LOG_FORMAT = f"{RECORD}%H{FIELD}%h{FIELD}%aI{FIELD}%s{FIELD}%b{END}"

MILESTONE = re.compile(r"^([A-Z]\d+(?:\.\d+)?)\s*:\s*(.+)$")
STAT = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
# Строки описания, которые к истории не относятся.
SKIP = re.compile(r"^(co-authored-by|signed-off-by):", re.IGNORECASE)
# Меньше стольких строк — мелкая доводка, а не новая возможность.
POLISH_LINES = 120

# Разделы и слова, по которым их узнать в заголовке коммита.
AREAS: list[tuple[str, tuple[str, ...]]] = [
    ("Советник", ("советник", "mcp")),
    ("Сон", ("сон",)),
    ("Итоги", ("итоги", "ретроспектив")),
    ("Поиск", ("поиск",)),
    ("Дневник", ("дневник", "сфер")),
    ("План", ("план",)),
    ("Персонаж", ("персонаж", "стат")),
    ("Уровни", ("уровн",)),
    ("Голос", ("голос", "диктовк", "whisper")),
    ("Задачи", ("задач", "бэклог", "сдача")),
    ("Таймер", ("таймер",)),
    ("Норма и стрик", ("норм", "стрик")),
    ("XP", ("xp",)),
    ("Цели", ("цел",)),
    ("Служба", ("служб", "бэкап", "запуск", "launchd")),
    ("Агент", ("агент", "подписк")),
    ("Веб", ("веб",)),
    ("Бот", ("бот", "telegram")),
]
FIXES = ("чин", "исправ", "не теряется", "fix", "баг", "ошибк")


@dataclass(frozen=True)
class Commit:
    hash: str
    short: str
    at: datetime
    subject: str
    # Заголовок без кода вехи: «M2: задачи текстом» → «задачи текстом».
    title: str
    milestone: str | None
    area: str | None
    kind: str  # milestone / feature / fix / polish
    points: list[str]
    files: int
    insertions: int
    deletions: int


@dataclass
class Day:
    day: date
    commits: list[Commit] = field(default_factory=list)

    @property
    def insertions(self) -> int:
        return sum(c.insertions for c in self.commits)

    @property
    def deletions(self) -> int:
        return sum(c.deletions for c in self.commits)


@dataclass(frozen=True)
class Devlog:
    days: list[Day]  # свежие сверху

    @property
    def commits(self) -> int:
        return sum(len(d.commits) for d in self.days)

    @property
    def milestones(self) -> int:
        return sum(1 for d in self.days for c in d.commits if c.milestone)

    @property
    def insertions(self) -> int:
        return sum(d.insertions for d in self.days)


def area_of(subject: str) -> str | None:
    """Раздел — по слову, которое встречается в заголовке раньше других. Слова ищутся с начала
    слова: иначе «персонаж» попадал бы в «Сон»."""
    lowered = subject.lower()
    best: tuple[int, str] | None = None
    for name, words in AREAS:
        for word in words:
            found = re.search(rf"(?<!\w){re.escape(word)}", lowered)
            if found and (best is None or found.start() < best[0]):
                best = (found.start(), name)
    return best[1] if best else None


def points_of(body: str) -> list[str]:
    """Пункты описания: «- …» вместе с продолжением на следующих строках."""
    points: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or SKIP.match(line):
            continue
        if line.startswith(("- ", "* ")):
            points.append(line[2:].strip())
        elif points and raw.startswith((" ", "\t")):
            points[-1] += " " + line
    return points


def parse(log: str) -> list[Commit]:
    commits = []
    for record in log.split(RECORD):
        if END not in record:
            continue
        head, tail = record.split(END, 1)
        parts = head.split(FIELD)
        if len(parts) < 5:
            continue
        full, short, stamp, subject, body = parts[:5]
        stat = STAT.search(tail)
        files, insertions, deletions = (
            (int(stat.group(1)), int(stat.group(2) or 0), int(stat.group(3) or 0))
            if stat
            else (0, 0, 0)
        )
        milestone = MILESTONE.match(subject)
        if milestone:
            kind = "milestone"
        elif any(word in subject.lower() for word in FIXES):
            kind = "fix"
        elif insertions + deletions < POLISH_LINES:
            kind = "polish"
        else:
            kind = "feature"
        title = milestone.group(2) if milestone else subject
        commits.append(
            Commit(
                hash=full,
                short=short,
                at=datetime.fromisoformat(stamp),
                subject=subject,
                title=title[:1].upper() + title[1:],
                milestone=milestone.group(1) if milestone else None,
                area=area_of(subject),
                kind=kind,
                points=points_of(body),
                files=files,
                insertions=insertions,
                deletions=deletions,
            )
        )
    return commits


def group(commits: list[Commit]) -> Devlog:
    """По дням — по местной дате коммита, свежие сверху и внутри дня тоже."""
    days: dict[date, Day] = {}
    for commit in sorted(commits, key=lambda c: c.at, reverse=True):
        day = commit.at.date()
        days.setdefault(day, Day(day)).commits.append(commit)
    return Devlog(list(days.values()))


async def load(repo: Path) -> Devlog:
    """История репозитория; пусто, если это не git или git не установлен."""
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo),
            "log",
            "--no-merges",
            f"--format={LOG_FORMAT}",
            "--shortstat",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return Devlog([])
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return Devlog([])
    return group(parse(stdout.decode(errors="replace")))
