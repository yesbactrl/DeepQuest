"""Общая часть агента: промпты, сборка запроса, журнал вызовов, перебор моделей.

Агент не ходит в БД: контекст получает аргументами, а журнал своих вызовов
(`AgentCallLog`) отдаёт наружу — сохраняет его сервисный слой.

Транспортов два: Claude API (`api.ApiAgent`) и Claude Code по подписке
(`subscription.SubscriptionAgent`). Они отличаются только методом `_call`.
"""

import base64
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

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

    @property
    def path(self) -> Path:
        return PROMPTS_DIR / f"{self.name}.md"

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
    """Агент не дал ответа: недоступен, модель отказалась или вернула мусор."""

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


@dataclass(frozen=True)
class AgentConfig:
    plan_model: str = "claude-haiku-5-5"
    # Если модель отказалась отвечать, пробуем следующую.
    fallback_model: str = "claude-opus-5-5"
    plan_effort: str = "medium"
    validate_model: str = "claude-opus-5-5"
    validate_effort: str = "medium"
    max_tokens: int = 16000


@dataclass(frozen=True)
class Route:
    """Какой промпт, какие модели по очереди и с каким effort."""

    prompt: Prompt
    models: tuple[str, ...]
    effort: str


class ModelRefused(Exception):
    """Модель отказалась отвечать: можно попробовать следующую из маршрута."""


class CallFailed(Exception):
    """Вызов не удался: следующая модель не поможет."""


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


class PromptedAgent(ABC):
    """Собирает запросы из промптов и контекста; как их доставить — решает `_call`."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config = config or AgentConfig()
        plan_models = dict.fromkeys((config.plan_model, config.fallback_model))
        self._plan = Route(Prompt.load("plan_task"), tuple(plan_models), config.plan_effort)
        self._validate = Route(
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
        return await self._run("plan_task", self._plan, content, [], PlanResult)

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
        return await self._run("plan_task_answer", self._plan, content, [], TasksResult)

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
        return await self._run("plan_task_revise", self._plan, "\n\n".join(parts), [], TaskDraft)

    async def validate_report(self, report: ReportContext) -> AgentResult[ValidationResult]:
        # Картинки идут перед текстом: так модель лучше их учитывает.
        images = [
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
        return await self._run(
            "validate_report", self._validate, render_report(report), images, ValidationResult
        )

    async def _run[T: BaseModel](
        self,
        kind: str,
        route: Route,
        text: str,
        images: list[dict[str, Any]],
        output_model: type[T],
    ) -> AgentResult[T]:
        content = [*images, {"type": "text", "text": text}]
        calls: list[AgentCallLog] = []
        for model in route.models:
            log = AgentCallLog(
                kind=kind,
                prompt_version=route.prompt.version,
                model=model,
                # Картинки в журнал не пишем, только их число.
                request={"effort": route.effort, "input": text, "images": len(images)},
            )
            calls.append(log)
            try:
                output = await self._call(route, model, content, output_model, log)
            except ModelRefused:
                logger.warning("Model %s refused %s: %s", model, kind, log.error)
                continue
            except CallFailed as exc:
                raise AgentError(log.error or str(exc), calls) from exc
            return AgentResult(output, calls)
        raise AgentError("Every model refused", calls)

    @abstractmethod
    async def _call[T: BaseModel](
        self,
        route: Route,
        model: str,
        content: list[dict[str, Any]],
        output_model: type[T],
        log: AgentCallLog,
    ) -> T:
        """Один запрос к модели. Заполняет `log`; бросает ModelRefused или CallFailed."""


class FallbackAgent:
    """Сначала основной агент, при сбое — запасной. Журнал вызовов общий."""

    def __init__(self, primary: TaskAgent, secondary: TaskAgent) -> None:
        self._primary = primary
        self._secondary = secondary

    async def _either[T](self, method: str, *args: Any) -> AgentResult[T]:
        try:
            return await getattr(self._primary, method)(*args)
        except AgentError as primary_error:
            logger.warning(
                "Primary agent failed on %s (%s), trying fallback", method, primary_error
            )
            try:
                result: AgentResult[T] = await getattr(self._secondary, method)(*args)
            except AgentError as secondary_error:
                raise AgentError(
                    str(secondary_error), primary_error.calls + secondary_error.calls
                ) from secondary_error
            return AgentResult(result.output, primary_error.calls + result.calls)

    async def plan_task(self, text: str, goals: Sequence[GoalContext]) -> AgentResult[PlanResult]:
        return await self._either("plan_task", text, goals)

    async def answer_clarification(
        self, text: str, question: str, answer: str, goals: Sequence[GoalContext]
    ) -> AgentResult[TasksResult]:
        return await self._either("answer_clarification", text, question, answer, goals)

    async def revise_task(
        self,
        text: str,
        current: CurrentTask,
        correction: str | None,
        goals: Sequence[GoalContext],
    ) -> AgentResult[TaskDraft]:
        return await self._either("revise_task", text, current, correction, goals)

    async def validate_report(self, report: ReportContext) -> AgentResult[ValidationResult]:
        return await self._either("validate_report", report)
