"""Проверить промпт plan_task на настоящем Claude API, без Telegram и без базы.

    uv run python -m deepquest.agent "надо бы глянуть, как люди льют на тиктоке"

Цели берутся демонстрационные. Каждый запуск — платный запрос к API (Haiku — доли цента).
"""

import asyncio
import sys

from deepquest.agent.client import AgentError
from deepquest.agent.schemas import GoalContext
from deepquest.agent.setup import create_agent, create_claude_client
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
    settings = AgentSettings()
    client = create_claude_client(settings)
    if client is None:
        print("Нет ключа Claude API: впиши ANTHROPIC_API_KEY в .env", file=sys.stderr)
        return 1
    try:
        result = await create_agent(settings, client).plan_task(text, DEMO_GOALS)
    except AgentError as exc:
        for call in exc.calls:
            print(f"{call.model}: {call.error}", file=sys.stderr)
        return 1
    finally:
        await client.close()
    print(result.output.model_dump_json(indent=2))
    for call in result.calls:
        status = call.error or "ok"
        print(
            f"{call.model}: {status}, {call.latency_ms} ms, "
            f"{call.tokens_in} → {call.tokens_out} токенов",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(" ".join(sys.argv[1:]))))
