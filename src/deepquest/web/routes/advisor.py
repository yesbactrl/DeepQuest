"""Советник: разговоры, ответы потоком (SSE) и память."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.db.models import AdvisorChat, User
from deepquest.services import advisor
from deepquest.services.advisor import AdvisorJobs
from deepquest.web.deps import ContextDep, SessionDep, UserDep, WebContext
from deepquest.web.schemas import (
    AdvisorChatDetailOut,
    AdvisorChatEdit,
    AdvisorChatIn,
    AdvisorChatOut,
    AdvisorInfoOut,
    AdvisorMessageIn,
    AdvisorMessageOut,
    AdvisorNoteIn,
    AdvisorNoteOut,
)

router = APIRouter(prefix="/api/advisor", tags=["advisor"])

# Пустой комментарий раз в столько секунд: соединение не рвётся, пока советник думает.
KEEPALIVE_S = 15.0


def _jobs(context: WebContext) -> AdvisorJobs:
    if context.advisor is None:
        raise HTTPException(503, "Советник недоступен: не найден Claude Code (claude).")
    return context.advisor


async def _chat(session: AsyncSession, user: User, chat_id: int) -> AdvisorChat:
    chat = await advisor.get_chat(session, user, chat_id)
    if chat is None:
        raise HTTPException(404, "Разговор не найден.")
    return chat


def _chat_out(chat: AdvisorChat, context: WebContext) -> AdvisorChatOut:
    running = context.advisor is not None and context.advisor.running(chat.id) is not None
    return AdvisorChatOut.model_validate(chat, from_attributes=True).model_copy(
        update={"running": running}
    )


@router.get("")
async def info(context: ContextDep) -> AdvisorInfoOut:
    return AdvisorInfoOut(
        available=context.advisor is not None,
        models=advisor.MODELS,
        default_model=advisor.DEFAULT_MODEL,
    )


@router.get("/chats")
async def list_chats(
    session: SessionDep, user: UserDep, context: ContextDep
) -> list[AdvisorChatOut]:
    return [_chat_out(chat, context) for chat in await advisor.list_chats(session, user)]


@router.post("/chats", status_code=201)
async def create_chat(
    body: AdvisorChatIn, session: SessionDep, user: UserDep, context: ContextDep
) -> AdvisorChatOut:
    return _chat_out(await advisor.create_chat(session, user, body.model), context)


@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: int, session: SessionDep, user: UserDep, context: ContextDep
) -> AdvisorChatDetailOut:
    chat = await _chat(session, user, chat_id)
    return AdvisorChatDetailOut(
        **_chat_out(chat, context).model_dump(),
        messages=[
            AdvisorMessageOut.model_validate(m) for m in await advisor.messages(session, chat)
        ],
    )


@router.patch("/chats/{chat_id}")
async def edit_chat(
    chat_id: int, body: AdvisorChatEdit, session: SessionDep, user: UserDep, context: ContextDep
) -> AdvisorChatOut:
    chat = await _chat(session, user, chat_id)
    try:
        advisor.update_chat(chat, body.title, body.model)
    except advisor.AdvisorError as exc:
        raise HTTPException(422, str(exc)) from None
    return _chat_out(chat, context)


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: int, session: SessionDep, user: UserDep) -> Response:
    await advisor.delete_chat(session, await _chat(session, user, chat_id))
    return Response(status_code=204)


@router.post("/chats/{chat_id}/messages", status_code=202)
async def send(
    chat_id: int, body: AdvisorMessageIn, session: SessionDep, user: UserDep, context: ContextDep
) -> AdvisorMessageOut:
    jobs = _jobs(context)
    chat = await _chat(session, user, chat_id)
    try:
        message = await jobs.send(session, chat, body.text)
    except advisor.AdvisorError as exc:
        raise HTTPException(409, str(exc)) from None
    return AdvisorMessageOut.model_validate(message)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/chats/{chat_id}/stream")
async def stream(
    chat_id: int, session: SessionDep, user: UserDep, context: ContextDep
) -> StreamingResponse:
    """Поток ответа: сначала всё, что уже написано, потом новые кусочки и `done`.
    Если ответа сейчас нет — сразу `idle`."""
    await _chat(session, user, chat_id)
    job = context.advisor.running(chat_id) if context.advisor else None

    async def events() -> AsyncIterator[str]:
        if job is None:
            yield _sse({"type": "idle"})
            return
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        job.listeners.add(queue)
        try:
            yield _sse(job.snapshot())
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event)
                if event["type"] == "done":
                    return
        finally:
            job.listeners.discard(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/notes")
async def list_notes(session: SessionDep, user: UserDep) -> list[AdvisorNoteOut]:
    return [AdvisorNoteOut.model_validate(n) for n in await advisor.list_notes(session, user)]


@router.post("/notes", status_code=201)
async def add_note(body: AdvisorNoteIn, session: SessionDep, user: UserDep) -> AdvisorNoteOut:
    try:
        note = await advisor.add_note(session, user, body.text)
    except advisor.AdvisorError as exc:
        raise HTTPException(422, str(exc)) from None
    return AdvisorNoteOut.model_validate(note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: int, session: SessionDep, user: UserDep) -> Response:
    if not await advisor.delete_note(session, user, note_id):
        raise HTTPException(404, "Заметка не найдена.")
    return Response(status_code=204)
