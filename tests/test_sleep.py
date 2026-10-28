from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.db.models import SleepKind, User, XpEvent, XpKind
from deepquest.services import sleep
from deepquest.services.proofs import ProofStore
from deepquest.services.sleep import SleepInput
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import FakeAgent

ME = 111
# Суббота 24 октября 2026, 20:00 по Москве.
NOW = datetime(2026, 10, 24, 17, 0, tzinfo=UTC)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


@pytest.fixture
async def user_id(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz = "Europe/Moscow"
        await session.commit()
        return user.id


async def _user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    assert user is not None
    return user


async def test_sleep_belongs_to_wake_day_and_is_local(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        night = await sleep.add_session(
            session, user, SleepInput(SleepKind.NIGHT, at(23, 23, 30), at(24, 7)), NOW
        )
        assert night.day == date(2026, 10, 24)
        # В базе — UTC: 23:30 по Москве — это 20:30 UTC.
        assert night.started_at.hour == 20
        assert sleep.to_local(user, night.started_at) == at(23, 23, 30)


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (at(24, 7), at(24, 6), "после того, как лёг"),
        (at(24, 7), at(24, 7, 3), "короче 5 минут"),
        (at(22, 7), at(24, 7), "20 часов"),
        (at(24, 21), at(24, 23), "ещё не закончился"),
        (at(24, 6), at(24, 9), "Пересекается с другим сном: 23:30–07:00, 24.10"),
    ],
)
async def test_sleep_validation(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    start: datetime,
    end: datetime,
    message: str,
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        await sleep.add_session(
            session, user, SleepInput(SleepKind.NIGHT, at(23, 23, 30), at(24, 7)), NOW
        )
        with pytest.raises(sleep.SleepError, match=message):
            await sleep.add_session(session, user, SleepInput(SleepKind.NAP, start, end), NOW)


async def test_edit_can_keep_own_time(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        night = await sleep.add_session(
            session, user, SleepInput(SleepKind.NIGHT, at(23, 23, 30), at(24, 7)), NOW
        )
        await sleep.edit_session(
            session, user, night, SleepInput(SleepKind.NIGHT, at(23, 23), at(24, 7), quality=8), NOW
        )
        assert night.quality == 8 and sleep.to_local(user, night.started_at) == at(23, 23)


async def test_overview_stats(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        user.sleep_goal_min = 480
        # Пт: ночь 23:00–07:00 (8 ч) и дневной сон час. Сб: ночь 01:00–06:00 (5 ч).
        for item in (
            SleepInput(SleepKind.NIGHT, at(22, 23), at(23, 7), quality=8),
            SleepInput(SleepKind.NAP, at(23, 14), at(23, 15)),
            SleepInput(SleepKind.NIGHT, at(24, 1), at(24, 6), quality=4),
        ):
            await sleep.add_session(session, user, item, NOW)

        result = await sleep.overview(session, user, 7, NOW)

    friday, saturday = result.days[1], result.days[0]
    assert (friday.night_min, friday.nap_min, friday.total_min) == (480, 60, 540)
    assert (saturday.total_min, saturday.bedtime, saturday.wake) == (300, at(24, 1), at(24, 6))
    stats = result.stats
    assert (stats.days, stats.avg_total_min, stats.avg_night_min) == (2, 420, 390)
    # Средний отбой 23:00 и 01:00 — полночь, а не полдень.
    assert stats.avg_bedtime == 0
    assert stats.avg_wake == 6 * 60 + 30
    assert stats.bedtime_spread_min == 60
    assert (stats.goal_met, stats.debt_min, stats.avg_quality) == (1, 180, 6.0)
    assert (stats.short.days, stats.enough.days) == (1, 1)


def test_goal_bounds() -> None:
    user = User(telegram_id=1, sleep_goal_min=480)
    sleep.set_goal(user, 450)
    assert user.sleep_goal_min == 450
    with pytest.raises(sleep.SleepError):
        sleep.set_goal(user, 60)


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, user_id: int
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(sessionmaker, ME, tmp_path / "dist", FakeAgent(), ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


async def test_sleep_api(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/sleep", json={"kind": "night", "start": "2026-10-20T23:30", "end": "2026-10-21T07:15"}
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert (item["start"], item["end"], item["day"], item["minutes"]) == (
        "2026-10-20T23:30:00",
        "2026-10-21T07:15:00",
        "2026-10-21",
        465,
    )

    clash = await client.post(
        "/api/sleep", json={"kind": "nap", "start": "2026-10-21T07:00", "end": "2026-10-21T08:00"}
    )
    assert clash.status_code == 422 and "Пересекается" in clash.json()["detail"]

    edited = await client.patch(
        f"/api/sleep/{item['id']}",
        json={
            "kind": "night",
            "start": "2026-10-20T23:00",
            "end": "2026-10-21T07:15",
            "quality": 7,
        },
    )
    assert edited.json()["minutes"] == 495

    assert (await client.patch("/api/sleep/goal", json={"goal_min": 450})).json() == {
        "goal_min": 450
    }
    overview = (await client.get("/api/sleep", params={"days": 366})).json()
    assert overview["goal_min"] == 450 and len(overview["days"]) == 1

    assert (await client.delete(f"/api/sleep/{item['id']}")).status_code == 204
    assert (await client.delete(f"/api/sleep/{item['id']}")).status_code == 404


# XP за сон


async def _sleep_xp(session: AsyncSession, user: User) -> dict[date, int]:
    rows = await session.execute(
        select(XpEvent.logical_date, func.sum(XpEvent.amount))
        .where(XpEvent.user_id == user.id, XpEvent.kind == XpKind.SLEEP)
        .group_by(XpEvent.logical_date)
    )
    return {day: amount for day, amount in rows if amount}


async def test_sleep_xp_once_per_day(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        night = await sleep.add_session(
            session, user, SleepInput(SleepKind.NIGHT, at(22, 23), at(23, 7)), NOW
        )
        assert await _sleep_xp(session, user) == {date(2026, 10, 23): 10}
        # Два дневных сна за день — всё равно +5 один раз.
        await sleep.add_session(
            session, user, SleepInput(SleepKind.NAP, at(23, 14), at(23, 15)), NOW
        )
        nap = await sleep.add_session(
            session, user, SleepInput(SleepKind.NAP, at(23, 17), at(23, 17, 30)), NOW
        )
        assert await _sleep_xp(session, user) == {date(2026, 10, 23): 15}

        # Ночь перенесли на другое утро: XP уходит из старого дня в новый.
        await sleep.edit_session(
            session, user, night, SleepInput(SleepKind.NIGHT, at(23, 23), at(24, 7)), NOW
        )
        assert await _sleep_xp(session, user) == {date(2026, 10, 23): 5, date(2026, 10, 24): 10}

        # Один дневной убрали — второй остаётся, +5 не снимается; второй убрали — снимается.
        await sleep.delete_session(session, user, nap)
        assert await _sleep_xp(session, user) == {date(2026, 10, 23): 5, date(2026, 10, 24): 10}
        friday = date(2026, 10, 23)
        [other] = await sleep.sessions_between(session, user, friday, friday)
        await sleep.delete_session(session, user, other)
        assert await _sleep_xp(session, user) == {date(2026, 10, 24): 10}


async def test_sleep_api_reports_xp(client: httpx.AsyncClient) -> None:
    night = {"kind": "night", "start": "2026-10-20T23:30", "end": "2026-10-21T07:15"}
    created = (await client.post("/api/sleep", json=night)).json()
    assert created["xp_delta"] == 10
    nap = {"kind": "nap", "start": "2026-10-21T14:00", "end": "2026-10-21T15:00"}
    assert (await client.post("/api/sleep", json=nap)).json()["xp_delta"] == 5
    # Правка того же дня ничего не добавляет.
    edited = (
        await client.patch(f"/api/sleep/{created['id']}", json={**night, "quality": 7})
    ).json()
    assert edited["xp_delta"] == 0
