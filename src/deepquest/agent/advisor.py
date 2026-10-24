"""Советник: разговор с Claude Code, у которого есть инструменты DeepQuest (MCP).

Один ответ — один процесс `claude -p`:
- `--session-id` у первого сообщения разговора, `--resume` у следующих: контекст разговора
  хранит Claude Code, каждый разговор — своя сессия;
- `--mcp-config` + `--strict-mcp-config` — только сервер DeepQuest (`deepquest mcp`),
  `--tools ""` — без файлов, терминала и интернета, `--allowedTools mcp__deepquest` —
  инструменты DeepQuest без запроса разрешений;
- `--setting-sources ""` — без CLAUDE.md, хуков и настроек пользователя;
- `--include-partial-messages` — текст приходит по кусочкам, веб показывает его сразу.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from deepquest.agent.subscription import API_CREDENTIAL_VARS

MCP_SERVER = "deepquest"
TOOL_PREFIX = f"mcp__{MCP_SERVER}__"
# Сколько ходов (вызовов инструментов) на один ответ: хватает на «посмотреть всё и ответить».
MAX_TURNS = 30
# Сколько ждать следующей строки от Claude Code: инструменты быстрые, а разбор записи
# дневника агентом — до полуминуты.
IDLE_TIMEOUT_S = 180.0
STDOUT_LIMIT = 16 * 1024 * 1024


@dataclass(frozen=True)
class Started:
    """Claude Code поднял сессию: теперь её можно продолжать через --resume."""


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolUse:
    name: str  # без префикса mcp__deepquest__


@dataclass(frozen=True)
class Done:
    text: str


ChatEvent = Started | TextDelta | ToolUse | Done


class ChatFailed(Exception):
    """Ответа нет: Claude Code не запустился, упал, кончились лимиты или вышло время."""


@dataclass(frozen=True)
class ChatRequest:
    session_id: str
    resume: bool
    model: str
    system: str
    text: str


class ChatBackend(Protocol):
    def reply(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...


@dataclass
class _Parser:
    """Строки stream-json → события. Между текстом до и после вызова инструментов — абзац."""

    text: list[str] = field(default_factory=list)
    gap: bool = False

    def feed(self, event: dict[str, Any]) -> list[ChatEvent]:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            return [Started()]
        if kind == "stream_event":
            inner = event.get("event") or {}
            if inner.get("type") == "content_block_start":
                block = inner.get("content_block") or {}
                if block.get("type") == "tool_use":
                    self.gap = bool(self.text)
                    name = str(block.get("name", ""))
                    return [ToolUse(name.removeprefix(TOOL_PREFIX))]
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    chunk = delta["text"]
                    if self.gap:
                        chunk = "\n\n" + chunk.lstrip("\n")
                        self.gap = False
                    self.text.append(chunk)
                    return [TextDelta(chunk)]
        if kind == "result":
            if event.get("is_error") or event.get("subtype") != "success":
                reason = event.get("result") or event.get("subtype") or "неизвестная ошибка"
                raise ChatFailed(f"Claude Code: {reason}")
            return [Done("".join(self.text).strip() or str(event.get("result") or "").strip())]
        return []


class ClaudeCodeChat:
    def __init__(
        self,
        executable: str,
        workdir: Path,
        mcp_command: list[str],
        idle_timeout_s: float = IDLE_TIMEOUT_S,
    ) -> None:
        self._executable = executable
        self._workdir = workdir
        self._idle_timeout_s = idle_timeout_s
        workdir.mkdir(parents=True, exist_ok=True)
        self._mcp_config = workdir / "mcp.json"
        server = {"command": mcp_command[0], "args": mcp_command[1:]}
        self._mcp_config.write_text(json.dumps({"mcpServers": {MCP_SERVER: server}}))

    def command(self, request: ChatRequest) -> list[str]:
        session = ["--resume", request.session_id] if request.resume else [
            "--session-id", request.session_id
        ]  # fmt: skip
        return [
            self._executable,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--mcp-config", str(self._mcp_config),
            "--tools", "",
            "--allowedTools", f"mcp__{MCP_SERVER}",
            "--max-turns", str(MAX_TURNS),
            "--model", request.model,
            "--append-system-prompt", request.system,
            *session,
        ]  # fmt: skip

    async def reply(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        message = {"type": "user", "message": {"role": "user", "content": request.text}}
        # С ключом в окружении Claude Code ушёл бы на оплату по API, а не по подписке.
        env = {k: v for k, v in os.environ.items() if k not in API_CREDENTIAL_VARS}
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(request),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
                env=env,
                limit=STDOUT_LIMIT,
            )
        except OSError as exc:
            raise ChatFailed(f"Не удалось запустить Claude Code: {exc}") from exc
        assert process.stdin and process.stdout and process.stderr
        parser = _Parser()
        finished = False
        try:
            process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
            await process.stdin.drain()
            process.stdin.close()
            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(), timeout=self._idle_timeout_s
                    )
                except TimeoutError as exc:
                    raise ChatFailed("Claude Code долго молчит — ответ прерван.") from exc
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for item in parser.feed(event):
                    if isinstance(item, Done):
                        finished = True
                    yield item
            if not finished:
                await process.wait()
                tail = (await process.stderr.read()).decode(errors="replace").strip()[-400:]
                raise ChatFailed(
                    f"Claude Code завершился без ответа ({process.returncode}): {tail}"
                )
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
