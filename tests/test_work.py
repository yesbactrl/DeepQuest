from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.db.models import (
    Task,
    TaskStatus,
    TimeEntry,
    User,
    Validation,
    ValidationVerdict,
    XpEvent,
    XpKind,
)
from deepquest.services import goals, tasks, timer, xp
from deepquest.services.days import logical_date, season_of
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from tests.conftest import FAKE_FILE_BYTES, BotHarness, agent_down, verdict

ME = 111
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


# Логический день и формула XP


def test_logical_day_ends_at_boundary_hour() -> None:
    # 01:30 по Москве при границе 04:00 — это ещё 19 октября.
    late_night = datetime(2026, 10, 19, 22, 30, tzinfo=UTC)
    assert logical_date(late_night, "Europe/Moscow", 4) == date(2026, 10, 19)
    assert logical_date(late_night, "Europe/Moscow", 0) == date(2026, 10, 20)
    assert season_of(date(2026, 10, 31)) == "2026-10"


@pytest.mark.parametrize(
    ("actual", "estimate", "mult", "kind", "honor", "amount"),
    [
        (120, 120, 1.5, ValidationVerdict.ACCEPTED, False, 180),  # пример из спеки
        (300, 60, 1.0, ValidationVerdict.ACCEPTED, False, 120),  # потолок — две оценки
        (60, 60, 1.0, ValidationVerdict.ACCEPTED, True, 48),  # на честном слове
        (60, 60, 1.5, ValidationVerdict.PARTIAL, False, 63),
        (60, 60, 2.0, ValidationVerdict.REJECTED, False, 0),
        (0, 60, 1.5, ValidationVerdict.ACCEPTED, False, 0),
    ],
)
def test_task_xp_formula(
    actual: int, estimate: int, mult: float, kind: ValidationVerdict, honor: bool, amount: int
) -> None:
    breakdown = xp.compute_task_xp(
        actual_min=actual, estimate_min=estimate, value_mult=mult, verdict=kind, honor_mode=honor
    )
    assert breakdown.amount == amount
    assert breakdown.capped == (actual > 2 * estimate)


# Сервис таймера


@dataclass
class Seed:
    user: User
    first: Task
    second: Task


async def _open_task(
    session: AsyncSession, user: User, title: str, minutes: int = 120, mult: float = 1.5
) -> Task:
    fields = TaskFields(title, f"Сделано: {title}", None, minutes, mult, "реальный шаг")
    task = await tasks.create_draft(session, user, fields, title, None)
    tasks.save_task(task)
    return task


@pytest.fixture
async def seed(sessionmaker: async_sessionmaker[AsyncSession]) -> Seed:
    """Онбординг пройден, в бэклоге две оценённые задачи."""
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.onboarded_at = T0
        income = await goals.create_goal(session, user, "Свой доход", "Не зависеть от зарплаты")
        first = await _open_task(session, user, "Запустить кампанию в TikTok")
        first.goal_id = income.id
        second = await _open_task(session, user, "Записать рилс", minutes=60, mult=1.0)
        await session.commit()
        return Seed(user, first, second)


async def test_timer_switches_and_counts_minutes(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, seed.user.id)
        first = await session.get(Task, seed.first.id)
        second = await session.get(Task, seed.second.id)
        assert user and first and second

        await timer.start(session, user, first, T0)
        result = await timer.start(session, user, second, T0 + timedelta(minutes=25))
        assert result.paused is first
        assert (first.status, second.status) == (TaskStatus.OPEN, TaskStatus.RUNNING)

        await timer.start(session, user, first, T0 + timedelta(minutes=40))
        await timer.finish(session, user, first, T0 + timedelta(minutes=70))

        assert await timer.total_minutes(session, first, T0 + timedelta(hours=5)) == 55
        assert await timer.total_minutes(session, second, T0 + timedelta(hours=5)) == 15
        assert first.status == TaskStatus.AWAITING_REPORT
        assert await timer.running_entry(session, user) is None


async def test_unestimated_task_cannot_start(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, seed.user.id)
        assert user
        task = await tasks.create_unestimated(session, user, "что-то сделать")
        tasks.save_task(task)
        with pytest.raises(timer.TimerError):
            await timer.start(session, user, task, T0)


async def test_dispute_writes_correction_not_rewrite(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        user = await session.get(User, seed.user.id)
        task = await session.get(Task, seed.first.id)
        assert user and task
        accepted = xp.compute_task_xp(
            actual_min=120,
            estimate_min=120,
            value_mult=1.5,
            verdict=ValidationVerdict.ACCEPTED,
            honor_mode=False,
        )
        partial = xp.compute_task_xp(
            actual_min=120,
            estimate_min=120,
            value_mult=1.5,
            verdict=ValidationVerdict.PARTIAL,
            honor_mode=False,
        )
        await xp.record_task_xp(session, user, task, accepted, T0)
        correction = await xp.record_task_xp(session, user, task, partial, T0)

        assert (correction.kind, correction.amount) == (XpKind.CORRECTION, 126 - 180)
        assert await xp.task_xp(session, task) == 126
        assert await xp.total_xp(session, user) == 126


# Бот: от «Старт» до XP


async def _rewind_timer(sessionmaker: async_sessionmaker[AsyncSession], minutes: int) -> None:
    """Будто таймер запустили `minutes` минут назад."""
    async with sessionmaker() as session:
        entries = list(await session.scalars(select(TimeEntry)))
        for entry in entries:
            entry.started_at -= timedelta(minutes=minutes)
            if entry.ended_at is not None:
                entry.ended_at -= timedelta(minutes=minutes)
        await session.commit()


async def _task(sessionmaker: async_sessionmaker[AsyncSession], task_id: int) -> Task:
    async with sessionmaker() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


async def _start_first_from_backlog(harness: BotHarness) -> None:
    await harness.send(ME, "/backlog")
    await harness.tap(ME, "1")
    await harness.tap(ME, texts.START_BUTTON)


async def test_start_done_report_and_xp(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations.append(verdict("accepted", "Кампания запущена — это реальный шаг."))

    await _start_first_from_backlog(harness)
    assert "⏱ <b>Запустить кампанию в TikTok</b>" in harness.last_text
    await _rewind_timer(sessionmaker, 120)

    await harness.tap(ME, texts.DONE_BUTTON)
    assert "2 ч по таймеру" in harness.last_text
    await harness.send(ME, "Запустил кампанию на $20, вот кабинет: https://ads.tiktok.com/c/1")

    [report] = harness.agent.reports
    assert report.actual_min == 120
    assert report.links == ("https://ads.tiktok.com/c/1",)
    assert report.goal == "Свой доход"
    assert not report.honor_mode
    assert harness.last_text.startswith("✅ Засчитано · +180 XP")
    assert "Кампания запущена — это реальный шаг." in harness.last_text
    assert "Всего: 180 XP" in harness.last_text

    await harness.tap(ME, texts.WHY_BUTTON)
    assert "<b>Почему 180 XP</b>" in harness.last_text
    assert "120 мин × 1.5 × 1 × 1 = 180 XP" in harness.last_text

    assert (await _task(sessionmaker, seed.first.id)).status == TaskStatus.DONE
    async with sessionmaker() as session:
        [event] = await session.scalars(select(XpEvent))
        assert (event.amount, event.kind, event.season) == (180, XpKind.TASK, "2026-10")


async def test_screenshot_proof_reaches_agent(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations.append(verdict())
    await _start_first_from_backlog(harness)
    await harness.tap(ME, texts.DONE_BUTTON)

    await harness.send_photo(ME, file_id="screen-1", caption="Кампания запущена")

    [report] = harness.agent.reports
    assert report.report_text == "Кампания запущена"
    assert [(img.media_type, img.data) for img in report.images] == [
        ("image/jpeg", FAKE_FILE_BYTES)
    ]
    assert not report.honor_mode


async def test_report_without_proof_is_honor_mode(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations.append(verdict())
    await _start_first_from_backlog(harness)
    await _rewind_timer(sessionmaker, 60)
    await harness.tap(ME, texts.DONE_BUTTON)

    await harness.send(ME, "Сделал, но скрина нет")

    assert harness.agent.reports[0].honor_mode
    # 60 мин × 1.5 × 1.0 × 0.8
    assert harness.last_text.startswith("✅ Засчитано · +72 XP")


async def test_pause_resume_and_switch(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _start_first_from_backlog(harness)
    await _rewind_timer(sessionmaker, 30)

    await harness.tap(ME, texts.PAUSE_BUTTON)
    assert "Всего по задаче: 30 мин" in harness.last_text
    await harness.tap(ME, texts.RESUME_BUTTON)
    assert "До этого по задаче: 30 мин" in harness.last_text

    # Запуск второй задачи ставит первую на паузу.
    await harness.send(ME, "/backlog")
    await harness.tap(ME, "2")
    await harness.tap(ME, texts.START_BUTTON)
    assert "«Запустить кампанию в TikTok» на паузе" in harness.last_text
    first = await _task(sessionmaker, seed.first.id)
    second = await _task(sessionmaker, seed.second.id)
    assert (first.status, second.status) == (TaskStatus.OPEN, TaskStatus.RUNNING)


async def test_commands_go_pause_done(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/pause")
    assert harness.last_text == texts.NO_TIMER
    await harness.send(ME, "/go")
    assert harness.last_text.startswith(texts.PICK_TASK)

    await harness.tap(ME, "1")
    await harness.tap(ME, texts.START_BUTTON)
    await harness.send(ME, "/go")
    assert "Таймер идёт с" in harness.last_text

    await harness.send(ME, "/pause")
    assert harness.last_text.startswith("⏸ Пауза")
    await harness.send(ME, "/done")
    assert harness.last_text == texts.NO_TIMER

    await harness.tap(ME, texts.RESUME_BUTTON)
    await harness.send(ME, "/done")
    assert "Что получилось?" in harness.last_text
    # Отчёт не сдан — /done просит его снова.
    await harness.send(ME, "/cancel")
    await harness.send(ME, "/done")
    assert "Что получилось?" in harness.last_text


async def test_done_without_timer_warns_about_zero(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await harness.send(ME, "/backlog")
    await harness.tap(ME, "1")

    await harness.tap(ME, texts.DONE_BUTTON)

    assert "Таймер по задаче не запускался" in harness.last_text


async def test_agent_down_then_recheck(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations += [agent_down(), verdict("partial", "Только изучение.")]
    await _start_first_from_backlog(harness)
    await _rewind_timer(sessionmaker, 60)
    await harness.tap(ME, texts.DONE_BUTTON)

    await harness.send_photo(ME, file_id="screen-1", caption="Посмотрел, как льют")
    assert harness.last_text == texts.REPORT_SAVED_AGENT_DOWN
    assert (await _task(sessionmaker, seed.first.id)).status == TaskStatus.AWAITING_REPORT

    await harness.tap(ME, texts.RECHECK_BUTTON)

    # Скрин скачан заново из отчёта.
    assert len(harness.agent.reports[-1].images) == 1
    assert harness.last_text.startswith("🟡 Засчитано частично · +63 XP")


async def test_dispute_once(sessionmaker: async_sessionmaker[AsyncSession], seed: Seed) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.validations += [
        verdict("rejected", "Не вижу запуска."),
        verdict("accepted", "Теперь вижу: кампания запущена."),
    ]
    await _start_first_from_backlog(harness)
    await _rewind_timer(sessionmaker, 120)
    await harness.tap(ME, texts.DONE_BUTTON)
    await harness.send(ME, "Всё сделал")
    assert harness.last_text.startswith("❌ Не засчитано · 0 XP")
    assert (await _task(sessionmaker, seed.first.id)).status == TaskStatus.REJECTED

    await harness.tap(ME, texts.DISPUTE_BUTTON)
    assert harness.last_text == texts.ASK_DISPUTE
    await harness.send(ME, "Кампания запущена, id 123, бюджет потрачен")

    disputed = harness.agent.reports[-1]
    assert disputed.dispute == "Кампания запущена, id 123, бюджет потрачен"
    assert disputed.previous_verdict == "rejected"
    # Без пруфа: 120 × 1.5 × 1.0 × 0.8 = 144
    assert harness.last_text.startswith("⚖️ Пересмотрел. ✅ Засчитано · +144 XP")
    with pytest.raises(AssertionError):
        harness.button(texts.DISPUTE_BUTTON)
    assert (await _task(sessionmaker, seed.first.id)).status == TaskStatus.DONE
    async with sessionmaker() as session:
        validations = list(await session.scalars(select(Validation.is_dispute)))
        assert validations == [False, True]
        amounts = list(await session.scalars(select(XpEvent.amount).order_by(XpEvent.id)))
        assert amounts == [0, 144]


async def test_running_task_shows_in_backlog(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await _start_first_from_backlog(harness)

    await harness.send(ME, "/backlog")

    assert "⏱ Запустить кампанию в TikTok" in harness.last_text
    await harness.tap(ME, "1")
    assert "Таймер идёт с" in harness.last_text
    harness.button(texts.PAUSE_BUTTON)


async def test_logical_date_of_award_uses_user_timezone(
    sessionmaker: async_sessionmaker[AsyncSession], seed: Seed
) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(User).where(User.id == seed.user.id).values(tz="Asia/Ho_Chi_Minh")
        )
        await session.commit()
        user = await session.get(User, seed.user.id)
        task = await session.get(Task, seed.first.id)
        assert user and task
        breakdown = xp.compute_task_xp(
            actual_min=60,
            estimate_min=60,
            value_mult=1.0,
            verdict=ValidationVerdict.ACCEPTED,
            honor_mode=False,
        )
        # 31 октября 22:00 UTC — во Вьетнаме уже 1 ноября 05:00, после границы дня.
        event = await xp.record_task_xp(
            session, user, task, breakdown, datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
        )
        assert (event.logical_date, event.season) == (date(2026, 11, 1), "2026-11")
