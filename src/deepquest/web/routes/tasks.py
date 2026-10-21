"""Задачи в вебе: тот же путь, что в боте (мысль → агент → карточка → таймер → отчёт → XP),
плюс ручная правка карточки."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.schemas import VALUE_MULTIPLIERS
from deepquest.db.models import Report, Task, TaskStatus, User
from deepquest.services import goals, planning, stats, tasks, timer, validation
from deepquest.services.planning import PlanOutcome
from deepquest.services.proofs import (
    MAX_UPLOAD_BYTES,
    extract_links,
    is_image,
    sniff_image_type,
)
from deepquest.services.tasks import MAX_ESTIMATE_MIN, MAX_TITLE_LEN, MIN_ESTIMATE_MIN
from deepquest.services.timer import TimerError
from deepquest.services.validation import ReportError, ReportInput, ValidationOutcome
from deepquest.web.deps import ContextDep, SessionDep, UserDep
from deepquest.web.schemas import (
    CheckOut,
    ClarifyIn,
    DisputeIn,
    PlanIn,
    PlanOutcomeOut,
    ProofOut,
    ReportOut,
    ReviseIn,
    ReviseOut,
    StartOut,
    TaskDetailOut,
    TaskEdit,
    TaskOut,
    TimeIn,
    TimerOut,
    ValidationOut,
    XpBreakdownOut,
)

router = APIRouter(prefix="/api", tags=["tasks"])

MAX_FILES = 5
MAX_RESULT_LEN = 1000
MAX_REASON_LEN = 200
EDITABLE = {TaskStatus.DRAFT, TaskStatus.OPEN, TaskStatus.RUNNING}

TASK_NOT_FOUND = "Задача не найдена."
WRONG_STATUS = "Это действие недоступно в текущем статусе задачи."
NOT_ESTIMATED = "Сначала нужна оценка: поправь карточку или попроси агента оценить заново."


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(message: str = WRONG_STATUS) -> HTTPException:
    return HTTPException(409, message)


async def _task(session: AsyncSession, user: User, task_id: int) -> Task:
    task = await tasks.get_task(session, user, task_id)
    if task is None:
        raise HTTPException(404, TASK_NOT_FOUND)
    return task


def _report_out(task: Task, report: Report) -> ReportOut:
    proofs = []
    for index, proof in enumerate(report.proofs):
        image = is_image(proof)
        url = f"/api/tasks/{task.id}/proofs/{index}" if image else proof.get("url")
        proofs.append(
            ProofOut(
                index=index,
                kind=proof["kind"],
                name=proof.get("name") or proof.get("url"),
                url=url,
                is_image=image,
            )
        )
    return ReportOut(
        text=report.text, honor_mode=report.honor_mode, created_at=report.created_at, proofs=proofs
    )


async def _detail(session: AsyncSession, task: Task) -> TaskDetailOut:
    now = _now()
    totals = (await stats.task_totals(session, [task], now))[task.id]
    report = await validation.latest_report(session, task)
    latest = await validation.latest_validation(session, task)
    explanation = await validation.explain(session, task)
    breakdown = None
    if explanation is not None:
        b = explanation.breakdown
        breakdown = XpBreakdownOut(
            actual_min=b.actual_min,
            estimate_min=b.estimate_min,
            counted_min=b.counted_min,
            capped=b.capped,
            value_mult=b.value_mult,
            verdict=b.verdict,
            validation_mult=b.validation_mult,
            honor_mode=b.honor_mode,
            proof_mult=b.proof_mult,
            amount=b.amount,
            weak_mult=b.weak_mult,
        )
    return TaskDetailOut(
        **TaskOut.of(task, totals).model_dump(),
        report=_report_out(task, report) if report else None,
        validation=ValidationOut(
            verdict=latest.verdict,
            reason=latest.reason,
            comment=latest.comment,
            is_dispute=latest.is_dispute,
            dispute_text=latest.dispute_text,
            created_at=latest.created_at,
        )
        if latest
        else None,
        breakdown=breakdown,
        can_dispute=await validation.can_dispute(session, task),
    )


async def _fresh_detail(session: AsyncSession, user: User, task_id: int) -> TaskDetailOut:
    # Перечитываем: после правки goal_id связь с целью должна обновиться.
    return await _detail(session, await _task(session, user, task_id))


async def _plan_out(session: AsyncSession, outcome: PlanOutcome) -> PlanOutcomeOut:
    totals = await stats.task_totals(session, outcome.tasks, _now())
    return PlanOutcomeOut(
        tasks=[TaskOut.of(task, totals[task.id]) for task in outcome.tasks],
        question=outcome.question,
        agent_failed=outcome.agent_failed,
    )


async def _check_out(session: AsyncSession, user: User, outcome: ValidationOutcome) -> CheckOut:
    goal = outcome.task.goal
    stat = goal.parent if goal is not None and goal.parent is not None else goal
    return CheckOut(
        task=await _fresh_detail(session, user, outcome.task.id),
        agent_failed=outcome.agent_failed,
        xp_delta=outcome.xp_delta,
        total_xp=outcome.total_xp,
        stat=stat.title if stat is not None else None,
        skill=goal.title if goal is not None and goal.parent is not None else None,
        weak_mult=outcome.breakdown.weak_mult if outcome.breakdown else 1.0,
    )


# Список, карточка, ручная правка


@router.get("/tasks")
async def list_tasks(
    session: SessionDep,
    user: UserDep,
    status: Annotated[list[TaskStatus] | None, Query()] = None,
    goal_id: int | None = None,
) -> list[TaskOut]:
    goal_ids = None
    if goal_id is not None:
        # Фильтр по цели включает её направления.
        goal = await goals.get_active_goal(session, user, goal_id)
        goal_ids = {goal_id, *(d.id for d in goal.children)} if goal else {goal_id}
    items = await tasks.list_tasks(session, user, status, goal_ids)
    totals = await stats.task_totals(session, items, _now())
    return [TaskOut.of(task, totals[task.id]) for task in items]


@router.get("/tasks/{task_id}")
async def get_task(task_id: int, session: SessionDep, user: UserDep) -> TaskDetailOut:
    return await _detail(session, await _task(session, user, task_id))


@router.patch("/tasks/{task_id}")
async def edit_task(
    task_id: int, body: TaskEdit, session: SessionDep, user: UserDep
) -> TaskDetailOut:
    """Ручная правка: агент предлагает оценку, последнее слово за пользователем."""
    task = await _task(session, user, task_id)
    if task.status not in EDITABLE:
        raise _conflict("Править можно черновик и задачу в работе.")
    changes = body.model_dump(exclude_unset=True)

    if "title" in changes:
        title = " ".join((changes["title"] or "").split())
        if not 1 <= len(title) <= MAX_TITLE_LEN:
            raise HTTPException(422, f"Название — от 1 до {MAX_TITLE_LEN} символов.")
        task.title = title
    if "expected_result" in changes:
        result = (changes["expected_result"] or "").strip()
        if len(result) > MAX_RESULT_LEN:
            raise HTTPException(422, f"Результат — до {MAX_RESULT_LEN} символов.")
        task.expected_result = result or None
    if "goal_id" in changes:
        goal_id = changes["goal_id"]
        if goal_id is not None and goal_id not in await goals.active_goal_ids(session, user):
            raise HTTPException(422, "Нет такой цели.")
        task.goal_id = goal_id
    if "estimate_min" in changes:
        estimate = changes["estimate_min"]
        if estimate is None or not MIN_ESTIMATE_MIN <= estimate <= MAX_ESTIMATE_MIN:
            raise HTTPException(422, f"Оценка — от {MIN_ESTIMATE_MIN} до {MAX_ESTIMATE_MIN} минут.")
        task.estimate_min = estimate
    if "value_mult" in changes:
        mult = changes["value_mult"]
        if mult not in VALUE_MULTIPLIERS:
            allowed = ", ".join(f"×{m:g}" for m in VALUE_MULTIPLIERS)
            raise HTTPException(422, f"Множитель — один из: {allowed}.")
        task.value_mult = mult
    if "mult_reason" in changes:
        reason = (changes["mult_reason"] or "").strip()
        if len(reason) > MAX_REASON_LEN:
            raise HTTPException(422, f"Пояснение к множителю — до {MAX_REASON_LEN} символов.")
        task.mult_reason = reason or None

    await session.flush()
    return await _fresh_detail(session, user, task.id)


# Агент: мысль, уточнение, правка словами


@router.post("/tasks/plan")
async def plan(
    body: PlanIn, session: SessionDep, user: UserDep, context: ContextDep
) -> PlanOutcomeOut:
    outcome = await planning.plan_from_text(session, context.agent, user, body.text.strip())
    return await _plan_out(session, outcome)


@router.post("/tasks/{task_id}/clarify")
async def clarify(
    task_id: int, body: ClarifyIn, session: SessionDep, user: UserDep, context: ContextDep
) -> PlanOutcomeOut:
    task = await _task(session, user, task_id)
    if task.status != TaskStatus.CLARIFYING:
        raise _conflict("Агент по этой задаче ничего не спрашивал.")
    outcome = await planning.answer_clarification(
        session, context.agent, user, task, body.answer.strip()
    )
    return await _plan_out(session, outcome)


@router.post("/tasks/{task_id}/revise")
async def revise(
    task_id: int, body: ReviseIn, session: SessionDep, user: UserDep, context: ContextDep
) -> ReviseOut:
    task = await _task(session, user, task_id)
    if task.status not in {TaskStatus.DRAFT, TaskStatus.OPEN}:
        raise _conflict("Поправить через агента можно черновик или задачу из бэклога.")
    correction = (body.correction or "").strip() or None
    revised = await planning.revise(session, context.agent, user, task, correction)
    return ReviseOut(task=await _fresh_detail(session, user, task_id), agent_failed=not revised)


# Решение по черновику


@router.post("/tasks/{task_id}/save")
async def save(task_id: int, session: SessionDep, user: UserDep) -> TaskDetailOut:
    task = await _task(session, user, task_id)
    try:
        tasks.save_task(task)
    except tasks.TaskError:
        raise _conflict("Сохранить можно только черновик.") from None
    return await _detail(session, task)


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: int, session: SessionDep, user: UserDep) -> TaskDetailOut:
    task = await _task(session, user, task_id)
    try:
        tasks.cancel_task(task)
    except tasks.TaskError:
        raise _conflict("Отменить можно черновик или задачу из бэклога.") from None
    return await _detail(session, task)


# Таймер


@router.get("/timer")
async def running_timer(session: SessionDep, user: UserDep) -> TimerOut | None:
    entry = await timer.running_entry(session, user)
    if entry is None:
        return None
    task = await _task(session, user, entry.task_id)
    return TimerOut(
        task_id=task.id,
        title=task.title,
        goal_path=goals.goal_path(task.goal) if task.goal else None,
        started_at=entry.started_at,
        before_min=await timer.total_minutes(session, task, entry.started_at),
    )


@router.post("/tasks/{task_id}/start")
async def start(task_id: int, session: SessionDep, user: UserDep) -> StartOut:
    task = await _task(session, user, task_id)
    if not task.is_estimated:
        raise _conflict(NOT_ESTIMATED)
    try:
        result = await timer.start(session, user, task, _now())
    except TimerError:
        raise _conflict("Запустить таймер можно только у задачи из бэклога.") from None
    return StartOut(
        task=await _detail(session, task),
        paused_task_id=result.paused.id if result.paused else None,
    )


@router.post("/tasks/{task_id}/pause")
async def pause(task_id: int, session: SessionDep, user: UserDep) -> TaskDetailOut:
    task = await _task(session, user, task_id)
    try:
        await timer.pause(session, user, task, _now())
    except TimerError:
        raise _conflict("Таймер по этой задаче не идёт.") from None
    return await _detail(session, task)


@router.post("/tasks/{task_id}/done")
async def done(task_id: int, session: SessionDep, user: UserDep) -> TaskDetailOut:
    task = await _task(session, user, task_id)
    if not task.is_estimated:
        raise _conflict(NOT_ESTIMATED)
    try:
        await timer.finish(session, user, task, _now())
    except TimerError:
        raise _conflict("Закончить можно задачу из бэклога или с идущим таймером.") from None
    return await _detail(session, task)


# Отчёт, проверка, оспаривание


@router.post("/tasks/{task_id}/report")
async def report(
    task_id: int,
    session: SessionDep,
    user: UserDep,
    context: ContextDep,
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
    # Сколько ушло на задачу; не указано — по таймеру, а без таймера — по оценке.
    spent_min: Annotated[int | None, Form(ge=1, le=24 * 60)] = None,
) -> CheckOut:
    task = await _task(session, user, task_id)
    if task.status != TaskStatus.AWAITING_REPORT:
        raise _conflict("Отчёт сдаётся после «Готово».")
    uploads = files or []
    if len(uploads) > MAX_FILES:
        raise HTTPException(422, f"Не больше {MAX_FILES} файлов.")
    text = text.strip()
    if not text and not uploads:
        raise HTTPException(422, "Напиши, что сделал, или приложи скриншот.")

    saved = []
    for upload in uploads:
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(422, f"Файл «{upload.filename}» больше 10 МБ.")
        mime_type = sniff_image_type(data)
        if mime_type is None:
            raise HTTPException(
                422, f"«{upload.filename}» — не картинка (нужен PNG, JPEG, GIF или WebP)."
            )
        saved.append(
            context.proofs.save_upload(task.id, upload.filename or "скриншот", mime_type, data)
        )

    report_input = ReportInput(text=text, links=extract_links(text), files=saved)
    images = await context.proofs.images(saved, context.telegram_download)
    try:
        outcome = await validation.submit_report(
            session, context.agent, user, task, report_input, images, _now(), spent_min
        )
    except ReportError:
        raise _conflict() from None
    return await _check_out(session, user, outcome)


@router.post("/tasks/{task_id}/recheck")
async def recheck(
    task_id: int, session: SessionDep, user: UserDep, context: ContextDep
) -> CheckOut:
    task = await _task(session, user, task_id)
    report = await validation.latest_report(session, task)
    if report is None or task.status != TaskStatus.AWAITING_REPORT:
        raise _conflict("Перепроверить можно отчёт, который агент ещё не проверил.")
    images = await context.proofs.images(report.proofs, context.telegram_download)
    outcome = await validation.retry(session, context.agent, user, task, images, _now())
    return await _check_out(session, user, outcome)


@router.post("/tasks/{task_id}/dispute")
async def dispute(
    task_id: int, body: DisputeIn, session: SessionDep, user: UserDep, context: ContextDep
) -> CheckOut:
    task = await _task(session, user, task_id)
    report = await validation.latest_report(session, task)
    if report is None:
        raise _conflict("По задаче нет отчёта.")
    images = await context.proofs.images(report.proofs, context.telegram_download)
    try:
        outcome = await validation.dispute(
            session, context.agent, user, task, body.argument.strip(), images, _now()
        )
    except ReportError:
        raise _conflict("Оспорить можно один раз и только проверенный отчёт.") from None
    return await _check_out(session, user, outcome)


@router.post("/tasks/{task_id}/time")
async def change_time(task_id: int, body: TimeIn, session: SessionDep, user: UserDep) -> CheckOut:
    task = await _task(session, user, task_id)
    try:
        outcome = await validation.change_time(session, user, task, body.spent_min, _now())
    except ReportError, TimerError:
        raise _conflict("Время правится после «Готово», когда таймер остановлен.") from None
    return await _check_out(session, user, outcome)


@router.get("/tasks/{task_id}/proofs/{index}")
async def proof_file(
    task_id: int, index: int, session: SessionDep, user: UserDep, context: ContextDep
) -> Response:
    task = await _task(session, user, task_id)
    report = await validation.latest_report(session, task)
    if report is None or not 0 <= index < len(report.proofs) or not is_image(report.proofs[index]):
        raise HTTPException(404, "Нет такого пруфа.")
    proof = report.proofs[index]
    if (path := context.proofs.upload_path(proof)) is not None:
        return FileResponse(path, media_type=proof["mime_type"])
    data = await context.proofs.read(proof, context.telegram_download)
    if data is None:
        raise HTTPException(404, "Скриншот недоступен.")
    return Response(data, media_type=proof["mime_type"])
