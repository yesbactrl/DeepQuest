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
    # XP только за рост: обычная работа по этой цели задачей не считается.
    growth_only: bool = False


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


# Дневник


# Все оценки дневника — по шкале 1–10.
Score = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


class DiarySphereNote(BaseModel):
    goal_id: int = Field(description="id цели из <goals>, про которую говорит запись")
    score: Score | None = Field(description="Как в этой сфере сейчас, 1–10; null, если не понять")
    good: str | None = Field(description="Что в этой сфере радует, до 80 символов; иначе null")
    bad: str | None = Field(
        description="Что огорчает или хочется изменить, до 80 символов; иначе null"
    )


class DiaryAnalysis(BaseModel):
    mood: Score | None = Field(
        description="Настроение 1–10 по шкале из инструкции; null, если не понять"
    )
    energy: Score | None = Field(description="Энергия 1–10; null, если не понять")
    drive: Score | None = Field(description="Желание действовать 1–10; null, если не понять")
    emotions: list[str] = Field(description="0–4 эмоции, по одному-два слова, со строчной буквы")
    factors: list[str] = Field(
        description="0–5 факторов, что повлияло на состояние, 1–3 слова каждый"
    )
    summary: str = Field(description="Суть записи одной строкой до 80 символов")
    spheres: list[DiarySphereNote] = Field(
        default_factory=list,
        description="Цели, о которых запись что-то говорит; пусто, если ни о какой",
    )


@dataclass(frozen=True)
class DiaryContext:
    """Запись дневника и что о ней нужно знать агенту."""

    text: str
    # «вторник, 21 октября, 08:15 (утро)» — по местному времени пользователя.
    written_at: str
    # Факторы и эмоции из прошлых записей, чаще встречавшиеся — первыми: агент берёт
    # те же формулировки, иначе статистика рассыплется на «плохой сон» и «не выспался».
    known_factors: tuple[str, ...] = ()
    known_emotions: tuple[str, ...] = ()
    # Сферы — цели пользователя с направлениями: агент раскладывает запись по ним.
    goals: tuple[GoalContext, ...] = ()
    # Цели, которые пользователь сам отметил у записи: про них агент пишет обязательно.
    chosen_goal_ids: tuple[int, ...] = ()


# Итоги периода


class ReviewAnalysis(BaseModel):
    summary: str = Field(description="Главное о периоде в 2–3 предложениях, на «ты»")
    wins: list[str] = Field(description="0–4 удачи периода, по одной фразе, с цифрами из итогов")
    struggles: list[str] = Field(description="0–4 вещи, которые буксовали или огорчали")
    patterns: list[str] = Field(
        description="0–3 связи: что сопровождало хорошие и плохие дни, только по данным"
    )
    next_steps: list[str] = Field(
        description="1–3 конкретных фокуса на следующий период, выполнимых и проверяемых"
    )


@dataclass(frozen=True)
class ReviewContext:
    """Итоги периода для разбора: цифры и записи уже собраны сервисом в текст."""

    # «неделя 19–25 октября (идёт, прошло 6 дней из 7)».
    period: str
    digest: str
    goals: tuple[GoalContext, ...] = ()
