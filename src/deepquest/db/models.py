from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, BigInteger, Enum, ForeignKey, Index, MetaData, String, Text, text
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


def _str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Enum хранится строкой его значения, без CHECK: новые значения не требуют миграции."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=16,
        values_callable=lambda members: [m.value for m in members],
    )


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
    status: Mapped[GoalStatus] = mapped_column(_str_enum(GoalStatus))
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


class TaskStatus(StrEnum):
    CLARIFYING = "clarifying"  # агент задал вопрос, ждём ответ
    DRAFT = "draft"  # карточка ждёт «Сохранить / Поправить / Отмена»
    OPEN = "open"  # в бэклоге
    RUNNING = "running"
    AWAITING_REPORT = "awaiting_report"
    DONE = "done"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    expected_result: Mapped[str | None] = mapped_column(Text)
    # Пусто, пока агент не оценил задачу (например, если API был недоступен).
    estimate_min: Mapped[int | None]
    value_mult: Mapped[float | None]
    mult_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TaskStatus] = mapped_column(_str_enum(TaskStatus), index=True)
    # Что пользователь написал на самом деле: агент видит это при каждой правке.
    source_text: Mapped[str] = mapped_column(Text)
    clarify_question: Mapped[str | None] = mapped_column(Text)
    clarify_answer: Mapped[str | None] = mapped_column(Text)
    # Вызов агента, который дал текущую оценку.
    agent_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_calls.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    goal: Mapped[Goal | None] = relationship(lazy="raise_on_sql")

    @property
    def is_estimated(self) -> bool:
        return self.estimate_min is not None and self.value_mult is not None


class AgentCall(Base):
    """Один запрос к Claude: для отладки, объяснения оценок и будущих eval-наборов."""

    __tablename__ = "agent_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    prompt_version: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    stop_reason: Mapped[str | None] = mapped_column(String(32))
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    latency_ms: Mapped[int]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TimeEntry(Base):
    """Отрезок работы по таймеру. Открытый отрезок (ended_at пуст) у пользователя один."""

    __tablename__ = "time_entries"
    __table_args__ = (
        Index(
            "uq_time_entries_running",
            "user_id",
            unique=True,
            sqlite_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    # manual — пауза, switched — запустили другую задачу, done — «Готово».
    stop_reason: Mapped[str | None] = mapped_column(String(16))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # [{"kind": "photo" | "document" | "link", "file_id"?, "mime_type"?, "url"?}]
    proofs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    honor_mode: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ValidationVerdict(StrEnum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    REJECTED = "rejected"


class Validation(Base):
    """Вердикт агента по отчёту. Оспаривание добавляет новую запись, старую не трогает."""

    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"))
    agent_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_calls.id", ondelete="SET NULL")
    )
    verdict: Mapped[ValidationVerdict] = mapped_column(_str_enum(ValidationVerdict))
    reason: Mapped[str] = mapped_column(Text)
    comment: Mapped[str] = mapped_column(Text)
    is_dispute: Mapped[bool]
    dispute_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class XpKind(StrEnum):
    TASK = "task"
    CORRECTION = "correction"  # пересчёт после оспаривания: разница к прошлому начислению


class XpEvent(Base):
    """Журнал XP: только дописывается. Уровни и суммы считаются из него."""

    __tablename__ = "xp_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"))
    kind: Mapped[XpKind] = mapped_column(_str_enum(XpKind))
    amount: Mapped[int]
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON)
    logical_date: Mapped[date]
    season: Mapped[str] = mapped_column(String(7), index=True)  # «2026-10»
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FsmRecord(Base):
    """Состояние диалога aiogram (FSM). Хранится в базе, чтобы сценарии переживали перезапуск."""

    __tablename__ = "fsm_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
