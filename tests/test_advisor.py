import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.advisor import (
    ChatEvent,
    ChatFailed,
    ChatRequest,
    ClaudeCodeChat,
    Done,
    Started,
    TextDelta,
    ToolUse,
    _Parser,
)
from deepquest.db.models import AdvisorChat, AdvisorMessage
from deepquest.services import advisor
from deepquest.services.advisor import AdvisorJobs
from deepquest.services.proofs import ProofStore
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import FakeAgent

ME = 111


class FakeChat:
    """Ответ по сценарию; `gate` держит ответ, пока тест не отпустит."""

    def __init__(self, *events: ChatEvent | Exception) -> None:
        self.events = list(events)
        self.requests: list[ChatRequest] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def reply(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for event in self.events:
            await self.gate.wait()
            if isinstance(event, Exception):
                raise event
            yield event


def stream_event(inner: dict[str, object]) -> dict[str, object]:
    return {"type": "stream_event", "event": inner}


def test_parser_joins_text_around_tools() -> None:
    parser = _Parser()
    lines = [
        {"type": "system", "subtype": "init", "session_id": "s"},
        stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Смотрю."}}
        ),
        stream_event(
            {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "mcp__deepquest__overview"},
            }
        ),
        stream_event(
            {
                "type": "content_block_delta",
                "delta": {"type": "input_json_delta", "partial_json": ""},
            }
        ),
        stream_event(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Сегодня зал."}}
        ),
        {"type": "result", "subtype": "success", "is_error": False, "result": "Сегодня зал."},
    ]
    events = [e for line in lines for e in parser.feed(line)]
    assert events == [
        Started(),
        TextDelta("Смотрю."),
        ToolUse("overview"),
        TextDelta("\n\nСегодня зал."),
        Done("Смотрю.\n\nСегодня зал."),
    ]
    with pytest.raises(ChatFailed, match="limit"):
        _Parser().feed(
            {"type": "result", "subtype": "success", "is_error": True, "result": "limit"}
        )


def test_command_starts_then_resumes_session(tmp_path: Path) -> None:
    chat = ClaudeCodeChat("claude", tmp_path, ["python", "-m", "deepquest", "mcp"])
    config = json.loads((tmp_path / "mcp.json").read_text())
    assert config == {
        "mcpServers": {"deepquest": {"command": "python", "args": ["-m", "deepquest", "mcp"]}}
    }
    first = chat.command(ChatRequest("abc", False, "claude-sonnet-5-5", "sys", "привет"))
    assert first[-2:] == ["--session-id", "abc"]
    assert first[first.index("--tools") + 1] == ""
    assert first[first.index("--allowedTools") + 1] == "mcp__deepquest"
    later = chat.command(ChatRequest("abc", True, "claude-sonnet-5-5", "sys", "ещё"))
    assert later[-2:] == ["--resume", "abc"]


@pytest.fixture
async def user_id(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz = "Europe/Moscow"
        await session.commit()
        return user.id


async def _wait_idle(jobs: AdvisorJobs, chat_id: int) -> None:
    for _ in range(100):
        if jobs.running(chat_id) is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("answer did not finish")


async def test_answer_is_saved_and_session_resumed(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    backend = FakeChat(Started(), ToolUse("overview"), TextDelta("Возьми #3."), Done("Возьми #3."))
    jobs = AdvisorJobs(sessionmaker, ME, backend)
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        await advisor.add_note(session, user, "Лучше работается после 11")
        chat = await advisor.create_chat(session, user)
        await jobs.send(session, chat, "Есть два часа — что делать?")
        chat_id = chat.id
    await _wait_idle(jobs, chat_id)

    first = backend.requests[0]
    assert not first.resume and first.model == advisor.DEFAULT_MODEL
    assert "Лучше работается после 11" in first.system and "## Сейчас" in first.system
    async with sessionmaker() as session:
        chat = await session.get(AdvisorChat, chat_id)
        assert chat is not None and chat.session_started
        assert chat.title == "Есть два часа — что делать?"
        reply = (await advisor.messages(session, chat))[-1]
        assert (reply.role, reply.text, reply.tools, reply.error) == (
            "assistant",
            "Возьми #3.",
            ["overview"],
            None,
        )
        await jobs.send(session, chat, "А потом?")
    await _wait_idle(jobs, chat_id)
    assert backend.requests[1].resume


async def test_failure_and_busy(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    backend = FakeChat(TextDelta("Начал"), ChatFailed("Claude Code: limit"))
    backend.gate.clear()
    jobs = AdvisorJobs(sessionmaker, ME, backend)
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        chat = await advisor.create_chat(session, user, "claude-opus-5-5")
        await jobs.send(session, chat, "Привет")
        with pytest.raises(advisor.AdvisorError, match="ещё отвечает"):
            await jobs.send(session, chat, "Ещё")
        chat_id = chat.id
    backend.gate.set()
    await _wait_idle(jobs, chat_id)
    async with sessionmaker() as session:
        reply = await session.scalar(
            select(AdvisorMessage).where(AdvisorMessage.role == "assistant")
        )
        assert reply is not None and reply.text == "Начал" and reply.error == "Claude Code: limit"


async def test_notes_limits(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> None:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        with pytest.raises(advisor.AdvisorError):
            await advisor.add_note(session, user, "   ")
        note = await advisor.add_note(session, user, "  по средам   зал ")
        assert note.text == "по средам зал"
        assert await advisor.delete_note(session, user, note.id)
        assert not await advisor.delete_note(session, user, note.id)


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, user_id: int
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeChat]]:
    backend = FakeChat(Started(), TextDelta("При"), TextDelta("вет"), Done("Привет"))
    backend.gate.clear()
    jobs = AdvisorJobs(sessionmaker, ME, backend)
    app = create_app(
        sessionmaker, ME, tmp_path / "dist", FakeAgent(), ProofStore(tmp_path), advisor_jobs=jobs
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client, backend


async def test_advisor_api_streams_answer(client: tuple[httpx.AsyncClient, FakeChat]) -> None:
    http, backend = client
    assert (await http.get("/api/advisor")).json()["available"] is True
    chat = (await http.post("/api/advisor/chats", json={})).json()
    assert chat["title"] == "Новый разговор"
    assert (
        await http.get(f"/api/advisor/chats/{chat['id']}/stream")
    ).text == 'data: {"type": "idle"}\n\n'

    sent = await http.post(f"/api/advisor/chats/{chat['id']}/messages", json={"text": "Привет"})
    assert sent.status_code == 202
    assert (await http.get(f"/api/advisor/chats/{chat['id']}")).json()["running"] is True

    async def release() -> None:
        await asyncio.sleep(0.05)
        backend.gate.set()

    asyncio.create_task(release())
    async with http.stream("GET", f"/api/advisor/chats/{chat['id']}/stream") as response:
        events = [
            json.loads(line.removeprefix("data: "))
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]
    assert events[0] == {"type": "snapshot", "text": "", "tools": []}
    assert [e["text"] for e in events if e["type"] == "text"] == ["При", "вет"]
    assert events[-1]["type"] == "done" and events[-1]["error"] is None

    detail = (await http.get(f"/api/advisor/chats/{chat['id']}")).json()
    assert [m["text"] for m in detail["messages"]] == ["Привет", "Привет"]
    assert detail["title"] == "Привет" and detail["running"] is False

    note = (await http.post("/api/advisor/notes", json={"text": "Спит до 9"})).json()
    assert [n["text"] for n in (await http.get("/api/advisor/notes")).json()] == ["Спит до 9"]
    assert (await http.delete(f"/api/advisor/notes/{note['id']}")).status_code == 204
    assert (
        await http.patch(f"/api/advisor/chats/{chat['id']}", json={"model": "gpt"})
    ).status_code == 422
    assert (await http.delete(f"/api/advisor/chats/{chat['id']}")).status_code == 204
