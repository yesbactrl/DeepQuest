"""Отчёт → вердикт агента → XP. Оспаривание — повторная проверка того же отчёта с аргументом.

Как и при оформлении задач, перед вызовом модели транзакция фиксируется: SQLite
не должен держать блокировку записи, пока ждём ответ.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.base import AgentError, TaskAgent
from deepquest.agent.schemas import ProofImage, ReportContext
from deepquest.db.models import Report, Task, TaskStatus, User, Validation, ValidationVerdict
from deepquest.services import character, tasks, timer, xp
from deepquest.services.agent_log import record_calls
from deepquest.services.xp import XpBreakdown

logger = logging.getLogger(__name__)

SELF_CHECK_REASON = "Засчитано без проверки агентом."


class ReportError(ValueError):
    """Отчёт или проверка невозможны в текущем статусе задачи."""


@dataclass(frozen=True)
class ReportInput:
    text: str
    links: list[str] = field(default_factory=list)
    # Файлы-пруфы из Telegram: {"kind": "photo" | "document", "file_id", "mime_type"}.
    files: list[dict[str, Any]] = field(default_factory=list)

    @property
    def honor_mode(self) -> bool:
        return not (self.links or self.files)

    @property
    def proofs(self) -> list[dict[str, Any]]:
        return [*self.files, *({"kind": "link", "url": url} for url in self.links)]


@dataclass
class ValidationOutcome:
    task: Task
    validation: Validation | None = None
    breakdown: XpBreakdown | None = None
    xp_delta: int = 0
    total_xp: int = 0
    agent_failed: bool = False


async def latest_report(session: AsyncSession, task: Task) -> Report | None:
    return await session.scalar(
        select(Report).where(Report.task_id == task.id).order_by(Report.id.desc()).limit(1)
    )


async def latest_validation(session: AsyncSession, task: Task) -> Validation | None:
    return await session.scalar(
        select(Validation)
        .where(Validation.task_id == task.id)
        .order_by(Validation.id.desc())
        .limit(1)
    )


async def can_dispute(session: AsyncSession, task: Task) -> bool:
    """Оспорить можно один раз: второй круг превратился бы в торг."""
    if task.status not in {TaskStatus.DONE, TaskStatus.REJECTED}:
        return False
    validation = await latest_validation(session, task)
    return validation is not None and not validation.is_dispute and not validation.self_check


async def submit_report(
    session: AsyncSession,
    agent: TaskAgent,
    user: User,
    task: Task,
    report_input: ReportInput,
    images: list[ProofImage],
    now: datetime,
    spent_min: int | None = None,
) -> ValidationOutcome:
    """`spent_min` — сколько ушло со слов пользователя. Не указано и таймер не запускали —
    считаем, что ушло столько, сколько заложено в оценке."""
    report = await _new_report(session, user, task, report_input, now, spent_min)
    return await _check(session, agent, user, task, report, images, now)


async def accept_without_check(
    session: AsyncSession,
    user: User,
    task: Task,
    report_input: ReportInput,
    now: datetime,
    spent_min: int | None = None,
) -> ValidationOutcome:
    """Засчитать задачу самому, без агента: вердикт «засчитано», XP по той же формуле.
    Пруф и тут бонус: со скрином или ссылкой ×1.1, без него ×1."""
    report = await _new_report(session, user, task, report_input, now, spent_min)
    validation = Validation(
        task_id=task.id,
        report_id=report.id,
        agent_call_id=None,
        verdict=ValidationVerdict.ACCEPTED,
        reason=SELF_CHECK_REASON,
        comment="",
        is_dispute=False,
        dispute_text=None,
        self_check=True,
    )
    session.add(validation)
    return await _award(session, user, task, report, validation, now)


async def _new_report(
    session: AsyncSession,
    user: User,
    task: Task,
    report_input: ReportInput,
    now: datetime,
    spent_min: int | None,
) -> Report:
    """Отчёт по задаче после «Готово». `spent_min` — сколько ушло со слов пользователя;
    не указано и таймер не запускали — считаем, что ушло столько, сколько в оценке."""
    if task.status != TaskStatus.AWAITING_REPORT:
        raise ReportError(f"Task {task.id} is {task.status}, not awaiting a report")
    if task.estimate_min is None or task.value_mult is None:
        raise ReportError(f"Task {task.id} has no estimate")
    by_timer = await timer.total_minutes(session, task, now)
    spent = spent_min if spent_min is not None else by_timer or task.estimate_min
    if spent != by_timer:
        await timer.set_total_minutes(session, user, task, spent, now)
    report = Report(
        task_id=task.id,
        text=report_input.text,
        proofs=report_input.proofs,
        honor_mode=report_input.honor_mode,
    )
    session.add(report)
    await session.flush()
    return report


async def _award(
    session: AsyncSession,
    user: User,
    task: Task,
    report: Report,
    validation: Validation,
    now: datetime,
) -> ValidationOutcome:
    """XP по вердикту: формула считает, журнал дописывается, задача закрывается."""
    assert task.estimate_min is not None and task.value_mult is not None
    breakdown = xp.compute_task_xp(
        actual_min=await timer.total_minutes(session, task, now),
        estimate_min=task.estimate_min,
        value_mult=task.value_mult,
        verdict=validation.verdict,
        honor_mode=report.honor_mode,
        weak_mult=await character.weak_mult(session, user, task, now),
    )
    event = await xp.record_task_xp(session, user, task, breakdown, now)
    rejected = validation.verdict == ValidationVerdict.REJECTED
    task.status = TaskStatus.REJECTED if rejected else TaskStatus.DONE
    return ValidationOutcome(
        task,
        validation=validation,
        breakdown=breakdown,
        xp_delta=event.amount,
        total_xp=await xp.total_xp(session, user),
    )


async def change_time(
    session: AsyncSession, user: User, task: Task, minutes: int, now: datetime
) -> ValidationOutcome:
    """Поправить, сколько ушло на задачу. У проверенной задачи XP пересчитывается тем же
    вердиктом — поправкой в журнале, как при оспаривании; агента заново не спрашиваем."""
    if task.status not in {TaskStatus.AWAITING_REPORT, TaskStatus.DONE, TaskStatus.REJECTED}:
        raise ReportError(f"Task {task.id} is {task.status}: time is changed after «Готово»")
    if task.estimate_min is None or task.value_mult is None:
        raise ReportError(f"Task {task.id} has no estimate")
    await timer.set_total_minutes(session, user, task, minutes, now)
    validation = await latest_validation(session, task)
    report = await latest_report(session, task)
    if task.status == TaskStatus.AWAITING_REPORT or validation is None or report is None:
        return ValidationOutcome(task)
    breakdown = xp.compute_task_xp(
        actual_min=await timer.total_minutes(session, task, now),
        estimate_min=task.estimate_min,
        value_mult=task.value_mult,
        verdict=validation.verdict,
        honor_mode=report.honor_mode,
        weak_mult=await character.weak_mult(session, user, task, now),
    )
    event = await xp.record_task_xp(session, user, task, breakdown, now)
    return ValidationOutcome(
        task,
        validation=validation,
        breakdown=breakdown,
        xp_delta=event.amount,
        total_xp=await xp.total_xp(session, user),
    )


async def retry(
    session: AsyncSession,
    agent: TaskAgent,
    user: User,
    task: Task,
    images: list[ProofImage],
    now: datetime,
) -> ValidationOutcome:
    """Повторная проверка, если в прошлый раз агент был недоступен."""
    report = await latest_report(session, task)
    if task.status != TaskStatus.AWAITING_REPORT or report is None:
        raise ReportError(f"Task {task.id} has no report waiting for a check")
    return await _check(session, agent, user, task, report, images, now)


async def dispute(
    session: AsyncSession,
    agent: TaskAgent,
    user: User,
    task: Task,
    argument: str,
    images: list[ProofImage],
    now: datetime,
) -> ValidationOutcome:
    previous = await latest_validation(session, task)
    report = await latest_report(session, task)
    if not await can_dispute(session, task) or previous is None or report is None:
        raise ReportError(f"Task {task.id} cannot be disputed")
    return await _check(
        session, agent, user, task, report, images, now, previous=previous, argument=argument
    )


def _goal_info(task: Task) -> tuple[str | None, str | None]:
    goal = task.goal
    if goal is None:
        return None, None
    path = f"{goal.parent.title} → {goal.title}" if goal.parent else goal.title
    return path, goal.why or (goal.parent.why if goal.parent else None)


async def _check(
    session: AsyncSession,
    agent: TaskAgent,
    user: User,
    task: Task,
    report: Report,
    images: list[ProofImage],
    now: datetime,
    previous: Validation | None = None,
    argument: str | None = None,
) -> ValidationOutcome:
    if task.estimate_min is None or task.value_mult is None:
        raise ReportError(f"Task {task.id} has no estimate")
    actual = await timer.total_minutes(session, task, now)
    goal, goal_why = _goal_info(task)
    files = [proof for proof in report.proofs if proof["kind"] != "link"]
    context = ReportContext(
        task=tasks.current_card(task),
        goal=goal,
        goal_why=goal_why,
        actual_min=actual,
        report_text=report.text,
        links=tuple(proof["url"] for proof in report.proofs if proof["kind"] == "link"),
        images=tuple(images),
        other_files=max(len(files) - len(images), 0),
        honor_mode=report.honor_mode,
        previous_verdict=previous.verdict.value if previous else None,
        previous_reason=previous.reason if previous else None,
        dispute=argument,
    )
    await session.commit()
    try:
        result = await agent.validate_report(context)
    except AgentError as exc:
        logger.warning("validate_report failed: %s", exc)
        await record_calls(session, user, exc.calls)
        return ValidationOutcome(task, agent_failed=True)

    call_id = await record_calls(session, user, result.calls)
    verdict = ValidationVerdict(result.output.verdict)
    validation = Validation(
        task_id=task.id,
        report_id=report.id,
        agent_call_id=call_id,
        verdict=verdict,
        reason=result.output.reason.strip(),
        comment=result.output.comment.strip(),
        is_dispute=argument is not None,
        dispute_text=argument,
    )
    session.add(validation)
    return await _award(session, user, task, report, validation, now)


@dataclass
class Explanation:
    breakdown: XpBreakdown
    validation: Validation
    task_total: int


async def explain(session: AsyncSession, task: Task) -> Explanation | None:
    """Данные для «Почему столько?»: последний расчёт и вердикт по задаче."""
    event = await xp.latest_event(session, task)
    validation = await latest_validation(session, task)
    if event is None or validation is None:
        return None
    return Explanation(
        breakdown=XpBreakdown.from_json(event.breakdown),
        validation=validation,
        task_total=await xp.task_xp(session, task),
    )
