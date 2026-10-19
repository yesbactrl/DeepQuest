import logging
import shutil
from dataclasses import dataclass, field

import anthropic

from deepquest.agent.api import ApiAgent
from deepquest.agent.base import AgentConfig, FallbackAgent, TaskAgent
from deepquest.agent.subscription import ClaudeCodeConfig, SubscriptionAgent
from deepquest.config import AgentSettings

logger = logging.getLogger(__name__)


@dataclass
class AgentHandle:
    agent: TaskAgent
    description: str
    clients: list[anthropic.AsyncAnthropic] = field(default_factory=list)

    async def aclose(self) -> None:
        for client in self.clients:
            await client.close()


def create_claude_client(settings: AgentSettings) -> anthropic.AsyncAnthropic | None:
    """Клиент Claude API или None, если учётных данных нет."""
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    client = anthropic.AsyncAnthropic(
        api_key=api_key, timeout=settings.agent_timeout_s, max_retries=2
    )
    # Клиент создаётся и без учётных данных, а падает уже на запросе (TypeError).
    # Ключ, токен или профиль `ant auth login` (кэш токенов) — что-то одно должно найтись.
    if client.api_key or client.auth_token or getattr(client, "_token_cache", None):
        return client
    logger.warning("Нет ключа Claude API (ANTHROPIC_API_KEY)")
    return None


def claude_code_config(settings: AgentSettings) -> ClaudeCodeConfig | None:
    executable = shutil.which(settings.claude_code_path)
    if executable is None:
        logger.warning(
            "Claude Code не найден (%s): задачи будут сохраняться без оценки. "
            "Укажи полный путь в CLAUDE_CODE_PATH.",
            settings.claude_code_path,
        )
        return None
    return ClaudeCodeConfig(
        executable=executable,
        workdir=settings.agent_workdir,
        timeout_s=settings.claude_code_timeout_s,
    )


def agent_config(settings: AgentSettings) -> AgentConfig:
    return AgentConfig(
        plan_model=settings.agent_plan_model,
        fallback_model=settings.agent_fallback_model,
        plan_effort=settings.agent_plan_effort,
        validate_model=settings.agent_validate_model,
        validate_effort=settings.agent_validate_effort,
    )


def build_agent(settings: AgentSettings) -> AgentHandle:
    config = agent_config(settings)
    if settings.agent_backend == "api":
        client = create_claude_client(settings)
        return AgentHandle(ApiAgent(client, config), "Claude API", [client] if client else [])

    subscription = SubscriptionAgent(claude_code_config(settings), config)
    if not settings.agent_api_fallback:
        return AgentHandle(subscription, "Claude Code по подписке")
    client = create_claude_client(settings)
    if client is None:
        logger.warning("AGENT_API_FALLBACK включён, но ключа API нет: работаем только по подписке")
        return AgentHandle(subscription, "Claude Code по подписке")
    return AgentHandle(
        FallbackAgent(subscription, ApiAgent(client, config)),
        "Claude Code по подписке, запасной — Claude API",
        [client],
    )
