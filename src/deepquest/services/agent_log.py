from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from deepquest.agent.client import AgentCallLog
from deepquest.db.models import AgentCall, User


async def record_calls(session: AsyncSession, user: User, calls: list[AgentCallLog]) -> int | None:
    """Пишет вызовы агента в журнал. Возвращает id последнего успешного — того, что дал ответ."""
    rows = [AgentCall(user_id=user.id, **asdict(call)) for call in calls]
    session.add_all(rows)
    await session.flush()
    return rows[-1].id if rows and rows[-1].error is None else None
