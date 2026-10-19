"""Вызовы Claude.

Агент не ходит в БД: контекст получает аргументами, а журнал своих вызовов
(`AgentCallLog`) отдаёт наружу — сохраняет его сервисный слой.
"""

import hashlib
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from deepquest.agent.schemas import CurrentTask, GoalContext, PlanResult, TaskDraft, TasksResult

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str

    @property
    def version(self) -> str:
        """Хэш текста: версия меняется сама при любой правке промпта."""
        return hashlib.sha256(self.text.encode()).hexdigest()[:8]

    @classmethod
    def load(cls, name: str) -> Prompt:
        return cls(name, (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


@dataclass
class AgentCallLog:
    kind: str
    prompt_version: str
    model: str
    request: dict[str, Any]
    latency_ms: int = 0
    response: dict[str, Any] | None = None
    stop_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None


@dataclass
class AgentResult[T]:
    output: T
    calls: list[AgentCallLog]


class AgentError(Exception):
    """Агент не дал ответа: API недоступен, модель отказалась или вернула мусор."""

    def __init__(self, reason: str, calls: list[AgentCallLog]) -> None:
        super().__init__(reason)
        self.calls = calls


class TaskAgent(Protocol):
    async def plan_task(
        self, text: str, goals: Sequence[GoalContext]
    ) -> AgentResult[PlanResult]: ...

    async def answer_clarification(
        self, text: str, question: str, answer: str, goals: Sequence[GoalContext]
    ) -> AgentResult[TasksResult]: ...

    async def revise_task(
        self,
        text: str,
        current: CurrentTask,
        correction: str | None,
        goals: Sequence[GoalContext],
    ) -> AgentResult[TaskDraft]: ...


@dataclass(frozen=True)
class AgentConfig:
    plan_model: str = "claude-haiku-5-5"
    # У Haiku нет серверного fallback при отказе, поэтому повторяем запрос на Opus сами.
    fallback_model: str = "claude-opus-5-5"
    plan_effort: str = "medium"
    max_tokens: int = 16000


def _block(tag: str, text: str) -> str:
    return f"<{tag}>\n{text.strip()}\n</{tag}>"


def render_goals(goals: Sequence[GoalContext]) -> str:
    if not goals:
        return _block("goals", "Целей пока нет.")
    lines = []
    for goal in goals:
        lines.append(f"- id={goal.id}: цель «{goal.title}». Зачем: {goal.why or 'не указано'}")
        lines += [
            f"  - id={d.id}: направление «{d.title}». Зачем: {d.why or 'не указано'}"
            for d in goal.directions
        ]
    return _block("goals", "\n".join(lines))


class ClaudeAgent:
    def __init__(
        self, client: anthropic.AsyncAnthropic | None, config: AgentConfig | None = None
    ) -> None:
        self._client = client
        self._config = config or AgentConfig()
        self._plan_prompt = Prompt.load("plan_task")

    async def plan_task(self, text: str, goals: Sequence[GoalContext]) -> AgentResult[PlanResult]:
        content = "\n\n".join(
            [
                render_goals(goals),
                _block("message", text),
                "Оформи задачи из сообщения или задай один уточняющий вопрос.",
            ]
        )
        return await self._run("plan_task", content, PlanResult)

    async def answer_clarification(
        self, text: str, question: str, answer: str, goals: Sequence[GoalContext]
    ) -> AgentResult[TasksResult]:
        content = "\n\n".join(
            [
                render_goals(goals),
                _block("message", text),
                _block("question", question),
                _block("answer", answer),
                "Ты уже задал уточняющий вопрос, и пользователь ответил. Больше не спрашивай: "
                "оформи задачи с лучшей формулировкой, какую можешь дать.",
            ]
        )
        return await self._run("plan_task_answer", content, TasksResult)

    async def revise_task(
        self,
        text: str,
        current: CurrentTask,
        correction: str | None,
        goals: Sequence[GoalContext],
    ) -> AgentResult[TaskDraft]:
        parts = [
            render_goals(goals),
            _block("message", text),
            _block("current_task", json.dumps(asdict(current), ensure_ascii=False, indent=2)),
        ]
        if correction:
            parts += [
                _block("correction", correction),
                "Пользователь просит поправить карточку задачи. Измени то, о чём просит правка, "
                "остальное оставь как есть.",
            ]
        else:
            parts.append("Оформи эту задачу заново: одну задачу, без вопросов.")
        return await self._run("plan_task_revise", "\n\n".join(parts), TaskDraft)

    def _models(self) -> list[str]:
        models = [self._config.plan_model]
        if self._config.fallback_model not in models:
            models.append(self._config.fallback_model)
        return models

    async def _run[T: BaseModel](
        self, kind: str, content: str, output_model: type[T]
    ) -> AgentResult[T]:
        prompt = self._plan_prompt
        calls: list[AgentCallLog] = []
        for model in self._models():
            log = AgentCallLog(
                kind=kind,
                prompt_version=prompt.version,
                model=model,
                request={"effort": self._config.plan_effort, "input": content},
            )
            calls.append(log)
            if self._client is None:
                log.error = "Claude API client is not configured"
                raise AgentError(log.error, calls)

            started = time.monotonic()
            try:
                response = await self._client.messages.create(
                    model=model,
                    max_tokens=self._config.max_tokens,
                    system=prompt.text,
                    messages=[{"role": "user", "content": content}],
                    output_config={
                        "effort": self._config.plan_effort,
                        "format": {
                            "type": "json_schema",
                            "schema": anthropic.transform_schema(output_model),
                        },
                    },
                )
            except anthropic.APIStatusError as exc:
                log.latency_ms = round((time.monotonic() - started) * 1000)
                log.error = f"HTTP {exc.status_code}: {exc.message}"
                raise AgentError(log.error, calls) from exc
            except anthropic.APIConnectionError as exc:
                log.latency_ms = round((time.monotonic() - started) * 1000)
                log.error = f"{type(exc).__name__}: {exc}"
                raise AgentError(log.error, calls) from exc
            except anthropic.AnthropicError as exc:
                # Например, не найдено ни ключа, ни профиля: клиент создаётся и без них,
                # а падает только на запросе.
                log.error = f"{type(exc).__name__}: {exc}"
                raise AgentError(log.error, calls) from exc

            log.latency_ms = round((time.monotonic() - started) * 1000)
            # Ответ может начинаться с блоков thinking: берём только текст.
            text = "".join(block.text for block in response.content if block.type == "text")
            log.stop_reason = response.stop_reason
            log.tokens_in = response.usage.input_tokens
            log.tokens_out = response.usage.output_tokens
            log.response = {"id": response.id, "text": text}

            if response.stop_reason == "refusal":
                category = response.stop_details.category if response.stop_details else None
                log.error = f"refusal: {category}"
                logger.warning("Model %s refused %s (%s), trying next model", model, kind, category)
                continue
            if response.stop_reason == "max_tokens":
                log.error = "Output hit max_tokens"
                raise AgentError(log.error, calls)
            try:
                output = output_model.model_validate_json(text)
            except ValidationError as exc:
                log.error = f"Invalid output: {exc}"
                raise AgentError(log.error, calls) from exc
            return AgentResult(output, calls)

        raise AgentError("Every model refused", calls)
