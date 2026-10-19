"""Что агент получает на вход и что обязан вернуть (structured outputs)."""

from dataclasses import dataclass, field
from typing import Literal, get_args

from pydantic import BaseModel, Field

ValueMult = Literal[0.5, 0.7, 1.0, 1.2, 1.5, 2.0]
VALUE_MULTIPLIERS: tuple[float, ...] = get_args(ValueMult)


class TaskDraft(BaseModel):
    title: str = Field(description="Конкретное действие с результатом, начинается с глагола")
    expected_result: str = Field(description="Что будет на выходе, проверяемо")
    goal_id: int | None = Field(description="id цели или направления из <goals>, иначе null")
    estimate_min: int = Field(description="Оценка в минутах")
    value_mult: ValueMult = Field(description="Множитель ценности по шкале из инструкции")
    mult_reason: str = Field(description="Почему такой множитель, 3–7 слов")


class PlanResult(BaseModel):
    clarify_question: str | None = Field(
        description="Один уточняющий вопрос, если непонятен результат; иначе null"
    )
    tasks: list[TaskDraft] = Field(description="Задачи; пустой список, если задан вопрос")


class TasksResult(BaseModel):
    tasks: list[TaskDraft] = Field(description="Задачи, хотя бы одна")


@dataclass(frozen=True)
class GoalContext:
    """Цель или направление, как их видит агент."""

    id: int
    title: str
    why: str | None
    directions: tuple[GoalContext, ...] = field(default=())


@dataclass(frozen=True)
class CurrentTask:
    """Карточка, которую пользователь просит поправить. Поля пусты, если оценки ещё нет."""

    title: str
    expected_result: str | None
    goal_id: int | None
    estimate_min: int | None
    value_mult: float | None
    mult_reason: str | None


Verdict = Literal["accepted", "partial", "rejected"]


class ValidationResult(BaseModel):
    verdict: Verdict = Field(description="accepted, partial или rejected по правилам из инструкции")
    reason: str = Field(description="Одно предложение: почему такой вердикт")
    comment: str = Field(description="Короткий живой ответ пользователю, 1–2 предложения, без XP")


@dataclass(frozen=True)
class ProofImage:
    media_type: str
    data: bytes


@dataclass(frozen=True)
class ReportContext:
    """Всё, что агент знает о сделанной задаче, когда проверяет отчёт."""

    task: CurrentTask
    goal: str | None  # «Свой доход → Арбитраж трафика»
    goal_why: str | None
    actual_min: int
    report_text: str
    links: tuple[str, ...]
    images: tuple[ProofImage, ...]
    other_files: int  # пруфы, которые агент не видит (например, PDF)
    honor_mode: bool
    # Заполнено при оспаривании: прошлый вердикт и аргумент пользователя.
    previous_verdict: str | None = None
    previous_reason: str | None = None
    dispute: str | None = None
