"""Вызовы Claude.

Агент не ходит в БД: контекст получает аргументами, а журнал своих вызовов
(`AgentCallLog`) отдаёт наружу — сохраняет его сервисный слой.
"""

import base64
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

from deepquest.agent.schemas import (
    CurrentTask,
    GoalContext,
    PlanResult,
    ReportContext,
    TaskDraft,
    TasksResult,
    ValidationResult,
)

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

    async def validate_report(self, report: ReportContext) -> AgentResult[ValidationResult]: ...


# Отказ модели по политике безопасности сервер повторяет на подходящей модели сам.
# У Haiku такого fallback нет (отказ останется отказом) — для неё есть свой повтор на Opus.
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class AgentConfig:
    plan_model: str = "claude-haiku-5-5"
    fallback_model: str = "claude-opus-5-5"
    plan_effort: str = "medium"
    validate_model: str = "claude-opus-5-5"
    validate_effort: str = "medium"
    max_tokens: int = 16000


@dataclass(frozen=True)
class _Route:
    prompt: Prompt
    models: tuple[str, ...]
    effort: str


def _block(tag: str, text: str) -> str:
    return f"<{tag}>\n{text.strip()}\n</{tag}>"


def _as_json(value: object) -> str:
    return json.dumps(asdict(value), ensure_ascii=False, indent=2)  # type: ignore[call-overload]


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


def render_report(report: ReportContext) -> str:
    parts = []
    if report.goal:
        parts.append(_block("goal", f"«{report.goal}». Зачем: {report.goal_why or 'не указано'}"))
    parts.append(_block("task", _as_json(report.task)))

    work = [
        f"Фактическое время по таймеру: {report.actual_min} мин "
        f"(оценка: {report.task.estimate_min or '—'} мин)."
    ]
    if report.images:
        work.append(f"Скриншоты: {len(report.images)}, приложены к сообщению.")
    if report.links:
        work.append("Ссылки: " + ", ".join(report.links))
    if report.other_files:
        work.append(f"Файлы, которые ты не видишь: {report.other_files}.")
    if report.honor_mode:
        work.append("Пруфа нет: режим «на честном слове».")
    parts.append(_block("work", "\n".join(work)))
    parts.append(_block("report", report.report_text or "(текста нет)"))

    if report.dispute is not None:
        parts.append(
            _block("previous_verdict", f"{report.previous_verdict}: {report.previous_reason}")
        )
        parts.append(_block("dispute", report.dispute))
        parts.append(
            "Пользователь оспаривает прошлый вердикт. Перепроверь отчёт с учётом аргумента."
        )
    else:
        parts.append("Вынеси вердикт по отчёту.")
    return "\n\n".join(parts)


class ClaudeAgent:
    def __init__(
        self, client: anthropic.AsyncAnthropic | None, config: AgentConfig | None = None
    ) -> None:
        self._client = client
        self._config = config = config or AgentConfig()
        plan_models = dict.fromkeys((config.plan_model, config.fallback_model))
        self._plan = _Route(Prompt.load("plan_task"), tuple(plan_models), config.plan_effort)
        self._validate = _Route(
            Prompt.load("validate_report"), (config.validate_model,), config.validate_effort
        )

    async def plan_task(self, text: str, goals: Sequence[GoalContext]) -> AgentResult[PlanResult]:
        content = "\n\n".join(
            [
                render_goals(goals),
                _block("message", text),
                "Оформи задачи из сообщения или задай один уточняющий вопрос.",
            ]
        )
        return await self._run("plan_task", self._plan, content, PlanResult)

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
        return await self._run("plan_task_answer", self._plan, content, TasksResult)

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
            _block("current_task", _as_json(current)),
        ]
        if correction:
            parts += [
                _block("correction", correction),
                "Пользователь просит поправить карточку задачи. Измени то, о чём просит правка, "
                "остальное оставь как есть.",
            ]
        else:
            parts.append("Оформи эту задачу заново: одну задачу, без вопросов.")
        return await self._run("plan_task_revise", self._plan, "\n\n".join(parts), TaskDraft)

    async def validate_report(self, report: ReportContext) -> AgentResult[ValidationResult]:
        text = render_report(report)
        # Картинки идут перед текстом: так модель лучше их учитывает.
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": base64.standard_b64encode(image.data).decode(),
                },
            }
            for image in report.images
        ]
        content.append({"type": "text", "text": text})
        return await self._run(
            "validate_report",
            self._validate,
            content,
            ValidationResult,
            log_input={"input": text, "images": len(report.images)},
        )

    async def _run[T: BaseModel](
        self,
        kind: str,
        route: _Route,
        content: str | list[dict[str, Any]],
        output_model: type[T],
        log_input: dict[str, Any] | None = None,
    ) -> AgentResult[T]:
        calls: list[AgentCallLog] = []
        for model in route.models:
            log = AgentCallLog(
                kind=kind,
                prompt_version=route.prompt.version,
                model=model,
                request={"effort": route.effort, **(log_input or {"input": content})},
            )
            calls.append(log)
            if self._client is None:
                log.error = "Claude API client is not configured"
                raise AgentError(log.error, calls)

            started = time.monotonic()
            try:
                response = await self._client.beta.messages.create(
                    model=model,
                    max_tokens=self._config.max_tokens,
                    system=route.prompt.text,
                    messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
                    output_config={
                        "effort": route.effort,  # type: ignore[typeddict-item]
                        "format": {
                            "type": "json_schema",
                            "schema": anthropic.transform_schema(output_model),
                        },
                    },
                    fallbacks="default",
                    betas=[SERVER_FALLBACK_BETA],
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
            # Если сработал серверный fallback, ответила другая модель — она в response.model.
            log.response = {"id": response.id, "model": response.model, "text": text}

            if response.stop_reason == "refusal":
                category = response.stop_details.category if response.stop_details else None
                log.error = f"refusal: {category}"
                logger.warning("Model %s refused %s (%s)", model, kind, category)
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
