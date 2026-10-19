from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import JSON, BigInteger, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from deepquest.db.types import UTCDateTime

# Явные имена ограничений нужны Alembic, чтобы batch-миграции SQLite могли их найти.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: UTCDateTime()}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    tz: Mapped[str] = mapped_column(String(64))
    # Час, в который заканчивается логический день (по поясу пользователя).
    day_boundary_hour: Mapped[int]
    daily_norm_min: Mapped[int]
    morning_at: Mapped[time]
    evening_at: Mapped[time]
    freezes_per_week: Mapped[int]
    onboarded_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FsmRecord(Base):
    """Состояние диалога aiogram (FSM). Хранится в базе, чтобы сценарии переживали перезапуск."""

    __tablename__ = "fsm_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
