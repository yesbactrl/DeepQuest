"""Поиск по задачам и дневнику.

Ищем в Python, а не через LIKE: SQLite сравнивает без учёта регистра только латиницу, а
записи — на русском. Пользователь один, задач и записей сотни: перебор занимает миллисекунды.
Каждое слово запроса должно найтись хоть где-то в задаче (или записи); «ё» и «е» равны.
Исходную мысль задачи не смотрим: из одного длинного сообщения агент делает несколько задач,
и по его тексту находились бы все они разом.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepquest.db.models import DiaryEntry, Goal, Report, Task, TaskStatus, User

MAX_QUERY_LEN = 200
LIMIT = 50
SNIPPET_LEN = 160
# Черновики и уточнения — ещё не задачи: в поиск не попадают.
HIDDEN = (TaskStatus.DRAFT, TaskStatus.CLARIFYING)


def normalize(text: str) -> str:
    return text.casefold().replace("ё", "е")


def words(query: str) -> list[str]:
    return normalize(query[:MAX_QUERY_LEN]).split()


@dataclass(frozen=True)
class Field:
    label: str  # где нашлось: «отчёт», «запись» …
    text: str


def _matches(fields: list[Field], terms: list[str]) -> bool:
    haystack = normalize(" \n".join(field.text for field in fields))
    return all(term in haystack for term in terms)


def snippet(fields: list[Field], terms: list[str]) -> tuple[str, str] | None:
    """Кусок текста вокруг первого совпадения: (где нашлось, «…текст…»)."""
    for field in fields:
        text = " ".join(field.text.split())
        folded = normalize(text)
        positions = [folded.find(term) for term in terms if term in folded]
        if not positions:
            continue
        at = min(positions)
        start = max(at - SNIPPET_LEN // 3, 0)
        end = min(start + SNIPPET_LEN, len(text))
        piece = text[start:end]
        return field.label, ("…" if start else "") + piece + ("…" if end < len(text) else "")
    return None


@dataclass(frozen=True)
class TaskHit:
    task: Task
    # Где нашлось и кусок текста; None — нашлось в названии, его и так видно.
    where: str | None
    snippet: str | None


@dataclass(frozen=True)
class SearchResult:
    tasks: list[TaskHit]
    entries: list[DiaryEntry]


def _task_fields(task: Task, reports: list[str]) -> list[Field]:
    fields = [Field("название", task.title)]
    if task.expected_result:
        fields.append(Field("результат", task.expected_result))
    if task.clarify_answer:
        fields.append(Field("уточнение", task.clarify_answer))
    fields += [Field("отчёт", text) for text in reports if text]
    return fields


def _entry_fields(entry: DiaryEntry) -> list[Field]:
    fields = [Field("запись", entry.text)]
    if entry.summary:
        fields.append(Field("суть", entry.summary))
    tags = [*entry.factors, *entry.emotions]
    if tags:
        fields.append(Field("теги", ", ".join(tags)))
    for sphere in entry.spheres:
        fields += [Field("сфера", note) for note in (sphere.good, sphere.bad) if note]
    return fields


async def search(session: AsyncSession, user: User, query: str) -> SearchResult:
    terms = words(query)
    if not terms:
        return SearchResult([], [])

    reports: dict[int, list[str]] = {}
    for task_id, text in await session.execute(
        select(Report.task_id, Report.text)
        .join(Task, Task.id == Report.task_id)
        .where(Task.user_id == user.id)
        .order_by(Report.id)
    ):
        reports.setdefault(task_id, []).append(text)

    tasks = await session.scalars(
        select(Task)
        .where(Task.user_id == user.id, Task.status.not_in(HIDDEN))
        .order_by(Task.updated_at.desc(), Task.id.desc())
        .options(selectinload(Task.goal).selectinload(Goal.parent))
    )
    in_title: list[TaskHit] = []
    elsewhere: list[TaskHit] = []
    for task in tasks:
        fields = _task_fields(task, reports.get(task.id, []))
        if not _matches(fields, terms):
            continue
        if _matches(fields[:1], terms):
            in_title.append(TaskHit(task, None, None))
        else:
            found = snippet(fields[1:], terms)
            elsewhere.append(TaskHit(task, *(found or (None, None))))

    entries = await session.scalars(
        select(DiaryEntry)
        .where(DiaryEntry.user_id == user.id)
        .order_by(DiaryEntry.created_at.desc(), DiaryEntry.id.desc())
    )
    found_entries = [entry for entry in entries if _matches(_entry_fields(entry), terms)]
    # Совпадения в названии важнее: их — первыми, дальше по свежести.
    return SearchResult((in_title + elsewhere)[:LIMIT], found_entries[:LIMIT])
