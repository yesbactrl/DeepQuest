"""Агент через Claude Code по подписке Pro/Max: `claude -p`, без ключа API.

Только для личного использования. Anthropic разрешает входить в неизменённый Claude Code
своей подпиской, но не пускать через неё запросы других людей. Если ботом начнут
пользоваться другие, нужно переключиться на API: AGENT_BACKEND=api.

Каждый вызов — отдельный процесс `claude -p` в пустой папке:
- `--safe-mode` не грузит CLAUDE.md, плагины, хуки, MCP и память, но вход по подписке работает;
- `--tools ""` — у модели нет инструментов, она только отвечает;
- `--json-schema` — ответ приходит проверенным JSON в поле `structured_output`;
- ввод в формате stream-json, чтобы передавать скриншоты так же, как в API.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from deepquest.agent.base import (
    AgentCallLog,
    AgentConfig,
    CallFailed,
    ModelRefused,
    PromptedAgent,
    Route,
)

# Структурированный ответ Claude Code собирает за пару ходов; больше — значит, что-то не так.
MAX_TURNS = 4
# С ключом в окружении Claude Code молча ушёл бы на оплату по API, а не по подписке.
API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True)
class ClaudeCodeConfig:
    executable: str
    workdir: Path
    timeout_s: float = 120.0


def _result_event(stdout: bytes) -> dict[str, Any] | None:
    """Последнее событие `result` из потока stream-json."""
    result = None
    for line in stdout.decode(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    return result


class SubscriptionAgent(PromptedAgent):
    def __init__(self, cli: ClaudeCodeConfig | None, config: AgentConfig | None = None) -> None:
        super().__init__(config)
        self._cli = cli
        if cli is not None:
            cli.workdir.mkdir(parents=True, exist_ok=True)

    def _command(self, route: Route, model: str, output_model: type[BaseModel]) -> list[str]:
        assert self._cli is not None
        return [
            self._cli.executable,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--safe-mode",
            "--strict-mcp-config",
            "--tools", "",
            "--no-session-persistence",
            "--max-turns", str(MAX_TURNS),
            "--model", model,
            "--effort", route.effort,
            "--system-prompt-file", str(route.prompt.path),
            "--json-schema", json.dumps(anthropic.transform_schema(output_model)),
        ]  # fmt: skip

    async def _call[T: BaseModel](
        self,
        route: Route,
        model: str,
        content: list[dict[str, Any]],
        output_model: type[T],
        log: AgentCallLog,
    ) -> T:
        if self._cli is None:
            log.error = "Claude Code CLI not found"
            raise CallFailed(log.error)

        message = {"type": "user", "message": {"role": "user", "content": content}}
        env = {k: v for k, v in os.environ.items() if k not in API_CREDENTIAL_VARS}
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command(route, model, output_model),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cli.workdir,
                env=env,
            )
        except OSError as exc:
            log.error = f"Cannot start Claude Code: {exc}"
            raise CallFailed(log.error) from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate((json.dumps(message, ensure_ascii=False) + "\n").encode()),
                timeout=self._cli.timeout_s,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            log.latency_ms = round((time.monotonic() - started) * 1000)
            log.error = f"Claude Code timed out after {self._cli.timeout_s:g}s"
            raise CallFailed(log.error) from exc
        log.latency_ms = round((time.monotonic() - started) * 1000)

        result = _result_event(stdout)
        if result is None:
            tail = stderr.decode(errors="replace").strip()[-500:]
            log.error = f"Claude Code exited with {process.returncode} and no result: {tail}"
            raise CallFailed(log.error)

        usage = result.get("usage") or {}
        tokens_in = sum(
            usage.get(key) or 0
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        log.tokens_in = tokens_in or None
        log.tokens_out = usage.get("output_tokens")
        log.stop_reason = result.get("stop_reason") or result.get("subtype")
        log.response = {
            "session_id": result.get("session_id"),
            "models": list((result.get("modelUsage") or {}).keys()),
            # Оценка Claude Code: по подписке не списывается, но полезна для сравнения с API.
            "estimated_cost_usd": result.get("total_cost_usd"),
            "result": result.get("structured_output") or result.get("result"),
        }

        if result.get("stop_reason") == "refusal":
            log.error = "refusal"
            raise ModelRefused(log.error)
        if result.get("is_error") or result.get("subtype") != "success":
            details = result.get("result") or result.get("api_error_status") or ""
            log.error = f"{result.get('subtype')}: {details}".strip()[:500]
            raise CallFailed(log.error)
        structured = result.get("structured_output")
        if structured is None:
            log.error = "Claude Code returned no structured output"
            raise CallFailed(log.error)
        try:
            return output_model.model_validate(structured)
        except ValidationError as exc:
            log.error = f"Invalid output: {exc}"
            raise CallFailed(log.error) from exc
