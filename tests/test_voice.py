from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import PlanResult, TasksResult
from deepquest.bot import texts
from deepquest.services import tasks
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.services.voice import (
    MAX_AUDIO_BYTES,
    MAX_VOICE_SECONDS,
    VoiceError,
    clean_transcript,
)
from deepquest.web.app import create_app
from tests.conftest import FAKE_FILE_BYTES, BotHarness, FakeAgent, FakeTranscriber, draft, verdict

ME = 111
SPOKEN = "Надо до пятницы дописать лендинг для курса"


@pytest.fixture
async def onboarded(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.onboarded_at = datetime.now(UTC)
        await session.commit()


def _harness(
    sessionmaker: async_sessionmaker[AsyncSession], *results: str | Exception
) -> tuple[BotHarness, FakeTranscriber]:
    transcriber = FakeTranscriber(*results)
    return BotHarness(sessionmaker, allowed_ids=[ME], transcriber=transcriber), transcriber


# Чистка расшифровки


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (
            "Оплатить хостинг до конца недели. Продолжение следует...",
            "Оплатить хостинг до конца недели.",
        ),
        ("Сходить в зал, спасибо за просмотр!", "Сходить в зал"),
        ("Смонтировать видео. Субтитры сделал DimaTorzok", "Смонтировать видео."),
        ("Продолжение следует...", ""),
        # Посреди фразы это обычные слова.
        ("Сделать субтитры к рилсу", "Сделать субтитры к рилсу"),
        ("Решить, продолжение следует ли снимать", "Решить, продолжение следует ли снимать"),
    ],
)
def test_phantom_tail_is_dropped(raw: str, clean: str) -> None:
    assert clean_transcript([raw]) == clean


def test_segments_are_joined() -> None:
    assert clean_transcript([" Разобрать почту,", " созвониться с подрядчиком. "]) == (
        "Разобрать почту, созвониться с подрядчиком."
    )


# Бот


async def test_voice_becomes_new_task(
    sessionmaker: async_sessionmaker[AsyncSession], onboarded: None
) -> None:
    harness, transcriber = _harness(sessionmaker, SPOKEN)
    harness.agent.plans.append(PlanResult(clarify_question=None, tasks=[draft("Дописать лендинг")]))

    await harness.send_voice(ME)

    assert transcriber.received == [FAKE_FILE_BYTES]
    assert texts.voice_heard(SPOKEN) in [screen.text for screen in harness.screens]
    [(kind, call)] = harness.agent.calls
    assert (kind, call["text"]) == ("plan_task", SPOKEN)
    assert "Дописать лендинг" in harness.last_text
    async with sessionmaker() as session:
        [task] = await tasks.list_tasks(session, await get_or_create_user(session, ME))
        assert task.source_text == SPOKEN


async def test_voice_answers_clarifying_question(
    sessionmaker: async_sessionmaker[AsyncSession], onboarded: None
) -> None:
    harness, _ = _harness(sessionmaker, "Запущенная кампания")
    harness.agent.plans.append(PlanResult(clarify_question="Что будет результатом?", tasks=[]))
    harness.agent.answers.append(TasksResult(tasks=[draft("Запустить кампанию")]))

    await harness.send(ME, "поизучать тикток")
    await harness.send_voice(ME)

    assert harness.agent.calls[1][0] == "answer"
    assert harness.agent.calls[1][1]["answer"] == "Запущенная кампания"
    assert "Запустить кампанию" in harness.last_text


async def test_voice_report(
    sessionmaker: async_sessionmaker[AsyncSession], onboarded: None
) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        fields = TaskFields("Записать рилс", "Рилс опубликован", None, 60, 1.0, "обычная работа")
        task = await tasks.create_draft(session, user, fields, "записать рилс", None)
        tasks.save_task(task)
        await session.commit()
    harness, _ = _harness(sessionmaker, "Записал и выложил рилс")
    harness.agent.validations.append(verdict())

    await harness.send(ME, "/backlog")
    await harness.tap(ME, "1")
    await harness.tap(ME, texts.START_BUTTON)
    await harness.tap(ME, texts.DONE_BUTTON)
    await harness.send_voice(ME)

    [report] = harness.agent.reports
    assert report.report_text == "Записал и выложил рилс"


@pytest.mark.parametrize(
    ("results", "seconds", "reply"),
    [
        (("",), 5, texts.VOICE_EMPTY),
        (
            (VoiceError("Не получилось прочитать запись."),),
            5,
            texts.voice_failed("Не получилось прочитать запись."),
        ),
        ((RuntimeError("whisper crashed"),), 5, texts.voice_failed()),
        ((), MAX_VOICE_SECONDS + 1, texts.VOICE_TOO_LONG),
    ],
)
async def test_voice_problems_are_explained(
    sessionmaker: async_sessionmaker[AsyncSession],
    onboarded: None,
    results: tuple[str | Exception, ...],
    seconds: int,
    reply: str,
) -> None:
    harness, transcriber = _harness(sessionmaker, *results)

    await harness.send_voice(ME, seconds=seconds)

    assert harness.last_text == reply
    assert harness.agent.calls == []
    assert transcriber.results == []


async def test_voice_off(sessionmaker: async_sessionmaker[AsyncSession], onboarded: None) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send_voice(ME)

    assert harness.last_text == texts.VOICE_OFF
    assert harness.agent.calls == []


async def test_stranger_voice_is_not_transcribed(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness, transcriber = _harness(sessionmaker, SPOKEN)

    await harness.send_voice(222)

    assert transcriber.received == []


# Веб


def _app(
    sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    transcriber: FakeTranscriber | None,
) -> FastAPI:
    proofs = ProofStore(tmp_path / "proofs")
    return create_app(sessionmaker, ME, tmp_path / "dist", FakeAgent(), proofs, None, transcriber)


@pytest.fixture
def transcriber() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, transcriber: FakeTranscriber
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(sessionmaker, tmp_path, transcriber)),
        base_url="http://127.0.0.1:8484",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


def _audio(data: bytes = b"webm audio") -> dict[str, tuple[str, bytes, str]]:
    return {"audio": ("voice.webm", data, "audio/webm")}


async def test_web_transcribes(client: httpx.AsyncClient, transcriber: FakeTranscriber) -> None:
    transcriber.results.append(SPOKEN)

    assert (await client.get("/api/voice")).json() == {"enabled": True}
    response = await client.post("/api/voice", files=_audio())

    assert response.status_code == 200
    assert response.json() == {"text": SPOKEN}
    assert transcriber.received == [b"webm audio"]


@pytest.mark.parametrize(
    ("result", "detail"),
    [
        ("", "Ничего не расслышал — попробуй ещё раз."),
        (VoiceError("Не получилось прочитать запись."), "Не получилось прочитать запись."),
    ],
)
async def test_web_transcription_problems(
    client: httpx.AsyncClient, transcriber: FakeTranscriber, result: str | Exception, detail: str
) -> None:
    transcriber.results.append(result)

    response = await client.post("/api/voice", files=_audio())

    assert response.status_code == 422
    assert response.json()["detail"] == detail


async def test_web_rejects_empty_and_huge_audio(
    client: httpx.AsyncClient, transcriber: FakeTranscriber
) -> None:
    assert (await client.post("/api/voice", files=_audio(b""))).status_code == 422
    huge = await client.post("/api/voice", files=_audio(b"0" * (MAX_AUDIO_BYTES + 1)))
    assert huge.status_code == 422
    assert transcriber.received == []


async def test_web_voice_off(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(sessionmaker, tmp_path, None)),
        base_url="http://127.0.0.1:8484",
        headers={"X-DeepQuest": "1"},
    ) as client:
        assert (await client.get("/api/voice")).json() == {"enabled": False}
        assert (await client.post("/api/voice", files=_audio())).status_code == 503


async def test_web_voice_needs_csrf_header(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, transcriber: FakeTranscriber
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(sessionmaker, tmp_path, transcriber)),
        base_url="http://127.0.0.1:8484",
    ) as bare:
        assert (await bare.post("/api/voice", files=_audio())).status_code == 403
    assert transcriber.received == []
