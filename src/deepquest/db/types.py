from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Момент времени в UTC.

    SQLite не хранит часовой пояс, поэтому в базу пишем наивное время в UTC,
    а наружу всегда отдаём aware datetime с tzinfo=UTC. Наивное время на входе —
    ошибка: по нему нельзя понять, в каком поясе оно было.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"Naive datetime is not allowed: {value!r}")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
