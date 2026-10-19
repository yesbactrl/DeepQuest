from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.db.models import Base, User


def test_migrations_match_models(db_path: Path) -> None:
    engine = create_sync_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []


def _user(**overrides: object) -> User:
    fields: dict[str, object] = {
        "telegram_id": 1,
        "tz": "UTC",
        "day_boundary_hour": 4,
        "daily_norm_min": 60,
        "morning_at": time(9),
        "evening_at": time(21),
        "freezes_per_week": 2,
    }
    return User(**(fields | overrides))


async def test_datetimes_come_back_in_utc(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    moscow_evening = datetime(2026, 10, 20, 23, 30, tzinfo=timezone(timedelta(hours=3)))
    async with sessionmaker() as session:
        session.add(_user(onboarded_at=moscow_evening))
        await session.commit()

    async with sessionmaker() as session:
        user = await session.get(User, 1)
        assert user is not None
        assert user.onboarded_at == datetime(2026, 10, 20, 20, 30, tzinfo=UTC)
        assert user.onboarded_at.tzinfo is UTC
        assert user.created_at.tzinfo is UTC


async def test_naive_datetime_is_rejected(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        session.add(_user(onboarded_at=datetime(2026, 10, 20, 12, 0)))
        with pytest.raises(StatementError, match="Naive datetime"):
            await session.commit()
