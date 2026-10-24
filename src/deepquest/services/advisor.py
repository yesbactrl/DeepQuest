"""Советник в вебе: разговоры, сообщения, память и ответы, которые идут в фоне.

Ответ советника — фоновая задача, а не запрос: она переживает уход со страницы и
обновление вкладки. Пока ответ пишется, веб подписывается на его поток и получает
текст по кусочкам; готовый ответ сохраняется в базе, даже если смотреть было некому.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.advisor import (
    ChatBackend,
    ChatFailed,
    ChatRequest,
    Done,
    Started,
    TextDelta,
    ToolUse,
)
from deepquest.agent.base import PROMPTS_DIR
from deepquest.db.models import AdvisorChat, AdvisorMessage, AdvisorNote, User
from deepquest.services.days import local_time
from deepquest.services.users import get_or_create_user

logger = logging.getLogger(__name__)

MODELS = {"claude-sonnet-5-5": "Sonnet — быстрее", "claude-opus-5-5": "Opus — глубже"}
DEFAULT_MODEL = "claude-sonnet-5-5"
NEW_TITLE = "Новый разговор"
TITLE_LEN = 60
MAX_TEXT_LEN = 8000
MAX_NOTE_LEN = 300
MAX_NOTES = 60
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


class AdvisorError(ValueError):
    """Действие невозможно: текст показывается пользователю как есть."""


def _now() -> datetime:
    return datetime.now(UTC)


# Разговоры и память


async def create_chat(session: AsyncSession, user: User, model: str | None = None) -> AdvisorChat:
    chat = AdvisorChat(
        user_id=user.id,
        title=NEW_TITLE,
        session_id=str(uuid.uuid4()),
        model=model if model in MODELS else DEFAULT_MODEL,
    )
    session.add(chat)
    await session.flush()
    return chat


async def list_chats(session: AsyncSession, user: User) -> list[AdvisorChat]:
    return list(
        await session.scalars(
            select(AdvisorChat)
            .where(AdvisorChat.user_id == user.id)
            .order_by(AdvisorChat.updated_at.desc(), AdvisorChat.id.desc())
        )
    )


async def get_chat(session: AsyncSession, user: User, chat_id: int) -> AdvisorChat | None:
    return await session.scalar(
        select(AdvisorChat).where(AdvisorChat.id == chat_id, AdvisorChat.user_id == user.id)
    )


async def messages(session: AsyncSession, chat: AdvisorChat) -> list[AdvisorMessage]:
    return list(
        await session.scalars(
            select(AdvisorMessage)
            .where(AdvisorMessage.chat_id == chat.id)
            .order_by(AdvisorMessage.id)
        )
    )


def update_chat(chat: AdvisorChat, title: str | None = None, model: str | None = None) -> None:
    if title is not None:
        title = " ".join(title.split())[:TITLE_LEN]
        if not title:
            raise AdvisorError("Название не может быть пустым.")
        chat.title = title
    if model is not None:
        if model not in MODELS:
            raise AdvisorError("Такой модели нет.")
        chat.model = model


async def delete_chat(session: AsyncSession, chat: AdvisorChat) -> None:
    await session.execute(delete(AdvisorChat).where(AdvisorChat.id == chat.id))


async def list_notes(session: AsyncSession, user: User) -> list[AdvisorNote]:
    return list(
        await session.scalars(
            select(AdvisorNote).where(AdvisorNote.user_id == user.id).order_by(AdvisorNote.id)
        )
    )


async def add_note(session: AsyncSession, user: User, text: str) -> AdvisorNote:
    text = " ".join(text.split())[:MAX_NOTE_LEN]
    if not text:
        raise AdvisorError("Пустую заметку не сохранить.")
    if len(await list_notes(session, user)) >= MAX_NOTES:
        raise AdvisorError(f"В памяти уже {MAX_NOTES} заметок — сначала убери устаревшие (forget).")
    note = AdvisorNote(user_id=user.id, text=text)
    session.add(note)
    await session.flush()
    return note


async def delete_note(session: AsyncSession, user: User, note_id: int) -> bool:
    result = await session.execute(
        delete(AdvisorNote).where(AdvisorNote.id == note_id, AdvisorNote.user_id == user.id)
    )
    return bool(getattr(result, "rowcount", 0))


def system_prompt(user: User, notes: list[AdvisorNote], now: datetime) -> str:
    """Промпт советника и то, что меняется от разговора к разговору: время и память."""
    local = local_time(user, now)
    parts = [
        (PROMPTS_DIR / "advisor.md").read_text(encoding="utf-8"),
        f"## Сейчас\n\n{WEEKDAYS[local.weekday()]}, {local:%d.%m.%Y %H:%M}, пояс {user.tz}.",
    ]
    if notes:
        parts.append(
            "## Что ты помнишь о пользователе\n\n"
            + "\n".join(f"- #{note.id}: {note.text}" for note in notes)
        )
    return "\n\n".join(parts)


# Ответы


@dataclass
class Job:
    """Ответ, который сейчас пишется: что уже пришло и кто смотрит."""

    chat_id: int
    text: str = ""
    tools: list[str] = field(default_factory=list)
    listeners: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        return {"type": "snapshot", "text": self.text, "tools": list(self.tools)}

    def publish(self, event: dict[str, Any]) -> None:
        for queue in self.listeners:
            queue.put_nowait(event)


class AdvisorJobs:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        owner_telegram_id: int,
        backend: ChatBackend,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._owner = owner_telegram_id
        self._backend = backend
        self._clock = clock
        self._jobs: dict[int, Job] = {}

    def running(self, chat_id: int) -> Job | None:
        return self._jobs.get(chat_id)

    async def send(self, session: AsyncSession, chat: AdvisorChat, text: str) -> AdvisorMessage:
        """Сохранить вопрос и начать ответ в фоне. Сессия вызывающего коммитится до старта."""
        text = text.strip()[:MAX_TEXT_LEN]
        if not text:
            raise AdvisorError("Напиши хоть пару слов.")
        if chat.id in self._jobs:
            raise AdvisorError("Советник ещё отвечает на прошлое сообщение.")
        message = AdvisorMessage(chat_id=chat.id, role="user", text=text, tools=[])
        session.add(message)
        if chat.title == NEW_TITLE:
            chat.title = " ".join(text.split())[:TITLE_LEN]
        chat.updated_at = self._clock()
        await session.flush()
        await session.commit()
        job = Job(chat.id)
        self._jobs[chat.id] = job
        job.task = asyncio.create_task(self._answer(job, text), name=f"advisor-{chat.id}")
        return message

    async def _with_session[T](self, work: Callable[[AsyncSession, User], Awaitable[T]]) -> T:
        async with self._sessionmaker() as session:
            user = await get_or_create_user(session, self._owner)
            result = await work(session, user)
            await session.commit()
            return result

    async def _answer(self, job: Job, text: str) -> None:
        started = time.monotonic()
        error: str | None = None

        async def prepare(session: AsyncSession, user: User) -> ChatRequest:
            chat = await session.get(AdvisorChat, job.chat_id)
            assert chat is not None
            return ChatRequest(
                session_id=chat.session_id,
                resume=chat.session_started,
                model=chat.model,
                system=system_prompt(user, await list_notes(session, user), self._clock()),
                text=text,
            )

        async def mark_started(session: AsyncSession, user: User) -> None:
            chat = await session.get(AdvisorChat, job.chat_id)
            if chat is not None:
                chat.session_started = True

        try:
            request = await self._with_session(prepare)
            async for event in self._backend.reply(request):
                if isinstance(event, Started):
                    if not request.resume:
                        await self._with_session(mark_started)
                elif isinstance(event, TextDelta):
                    job.text += event.text
                    job.publish({"type": "text", "text": event.text})
                elif isinstance(event, ToolUse):
                    job.tools.append(event.name)
                    job.publish({"type": "tool", "name": event.name})
                elif isinstance(event, Done):
                    job.text = event.text
        except ChatFailed as exc:
            error = str(exc)
        except asyncio.CancelledError:
            error = "Ответ прерван: DeepQuest перезапускался."
        except Exception as exc:  # чтобы ответ не повис в «пишет…» навсегда
            logger.exception("Advisor answer failed")
            error = f"Не получилось: {exc}"
        finally:
            latency = round((time.monotonic() - started) * 1000)

            async def save(session: AsyncSession, user: User) -> int:
                reply = AdvisorMessage(
                    chat_id=job.chat_id,
                    role="assistant",
                    text=job.text,
                    tools=job.tools,
                    error=error,
                    latency_ms=latency,
                )
                session.add(reply)
                chat = await session.get(AdvisorChat, job.chat_id)
                if chat is not None:
                    chat.updated_at = self._clock()
                await session.flush()
                return reply.id

            message_id = None
            with contextlib.suppress(Exception):
                # Разговор могли удалить, пока шёл ответ: сохранять тогда некуда.
                message_id = await asyncio.shield(self._with_session(save))
            self._jobs.pop(job.chat_id, None)
            job.publish({"type": "done", "message_id": message_id, "error": error})

    async def aclose(self) -> None:
        for job in list(self._jobs.values()):
            if job.task is not None:
                job.task.cancel()
        tasks = [job.task for job in self._jobs.values() if job.task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
