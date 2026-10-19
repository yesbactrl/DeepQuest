"""Проверить промпт plan_task на настоящей модели, без Telegram и без базы.

    uv run python -m deepquest.agent "надо бы глянуть, как люди льют на тиктоке"

Бэкенд — как у бота (AGENT_BACKEND в .env): по умолчанию Claude Code по подписке.
Цели берутся демонстрационные.
"""

import asyncio
import logging
import sys

from deepquest.agent.base import AgentError
from deepquest.agent.schemas import GoalContext
from deepquest.agent.setup import build_agent
from deepquest.config import AgentSettings

DEMO_GOALS = [
    GoalContext(
        id=1,
        title="Свой доход",
        why="Хочу не зависеть от зарплаты и пробовать свои идеи",
        directions=(
            GoalContext(id=2, title="Арбитраж трафика", why=None),
            GoalContext(id=3, title="Рилсы", why="Набрать аудиторию"),
        ),
    ),
    GoalContext(id=4, title="Здоровье", why="Чтобы хватало энергии на всё остальное"),
]


async def main(text: str) -> int:
    handle = build_agent(AgentSettings())
    print(f"Агент: {handle.description}", file=sys.stderr)
    try:
        result = await handle.agent.plan_task(text, DEMO_GOALS)
    except AgentError as exc:
        for call in exc.calls:
            print(f"{call.model}: {call.error}", file=sys.stderr)
        return 1
    finally:
        await handle.aclose()
    print(result.output.model_dump_json(indent=2))
    for call in result.calls:
        print(
            f"{call.model}: {call.error or 'ok'}, {call.latency_ms} ms, "
            f"{call.tokens_in} → {call.tokens_out} токенов",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]))))
