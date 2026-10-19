from datetime import UTC, datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Goal(Base):
    """Цель (`parent_id` пуст) или направление внутри цели. Дерево — ровно два уровня."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(80))
    # «Зачем» обязательно у цели и необязательно у направления. Агент оценивает задачи по нему.
    why: Mapped[str | None] = mapped_column(Text)
    status: Mapped[GoalStatus] = mapped_column(
        Enum(
            GoalStatus,
            native_enum=False,
            length=16,
            values_callable=lambda statuses: [s.value for s in statuses],
        )
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    archived_at: Mapped[datetime | None]

    # Async-сессия не умеет подгружать связи лениво: всё нужное грузим явно (selectinload).
    parent: Mapped[Goal | None] = relationship(
        back_populates="children", remote_side=[id], lazy="raise_on_sql"
    )
    children: Mapped[list[Goal]] = relationship(
        back_populates="parent", order_by=id, lazy="raise_on_sql"
    )

    @property
    def is_direction(self) -> bool:
        return self.parent_id is not None

    @property
    def active_children(self) -> list[Goal]:
        return [child for child in self.children if child.status == GoalStatus.ACTIVE]


class FsmRecord(Base):
    """Состояние диалога aiogram (FSM). Хранится в базе, чтобы сценарии переживали перезапуск."""

    __tablename__ = "fsm_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
