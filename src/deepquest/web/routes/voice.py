"""Голосовой ввод в вебе: браузер записывает звук, сервер распознаёт тем же Whisper, что и бот.

Каждая расшифровка сохраняется в короткую историю: если поле закрылось или вкладку обновили,
пока шло распознавание, текст не пропадёт — его можно вставить из «Последних диктовок».
"""

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from deepquest.services import voice
from deepquest.services.voice import MAX_AUDIO_BYTES, VoiceError
from deepquest.web.deps import ContextDep, SessionDep, UserDep
from deepquest.web.schemas import TranscriptOut, VoiceStatusOut

router = APIRouter(prefix="/api", tags=["voice"])


@router.get("/voice")
async def status(context: ContextDep) -> VoiceStatusOut:
    return VoiceStatusOut(enabled=context.transcriber is not None)


@router.post("/voice")
async def transcribe(
    audio: Annotated[UploadFile, File()],
    context: ContextDep,
    session: SessionDep,
    user: UserDep,
) -> TranscriptOut:
    if context.transcriber is None:
        raise HTTPException(503, "Голосовой ввод выключен (VOICE_ENABLED в .env).")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(422, f"Запись больше {MAX_AUDIO_BYTES // 1024 // 1024} МБ.")
    if not data:
        raise HTTPException(422, "Запись пустая.")
    try:
        text = await context.transcriber.transcribe(data)
    except VoiceError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not text:
        raise HTTPException(422, "Ничего не расслышал — попробуй ещё раз.")
    transcript = await voice.remember(session, user, text)
    # Фиксируем сразу: если браузер уже ушёл со страницы, ответ никто не получит,
    # а расшифровка должна остаться в истории.
    await session.commit()
    return TranscriptOut(id=transcript.id, text=transcript.text, created_at=transcript.created_at)


@router.get("/voice/history")
async def recent(session: SessionDep, user: UserDep) -> list[TranscriptOut]:
    return [
        TranscriptOut(id=t.id, text=t.text, created_at=t.created_at)
        for t in await voice.history(session, user)
    ]
