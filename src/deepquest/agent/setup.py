import logging

import anthropic

from deepquest.agent.client import AgentConfig, ClaudeAgent
from deepquest.config import AgentSettings

logger = logging.getLogger(__name__)


def create_claude_client(settings: AgentSettings) -> anthropic.AsyncAnthropic | None:
    """Клиент Claude API или None, если учётных данных нет — тогда бот работает без оценок."""
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    client = anthropic.AsyncAnthropic(
        api_key=api_key, timeout=settings.agent_timeout_s, max_retries=2
    )
    # Клиент создаётся и без учётных данных, а падает уже на запросе (TypeError).
    # Ключ, токен или профиль `ant auth login` (кэш токенов) — что-то одно должно найтись.
    if client.api_key or client.auth_token or getattr(client, "_token_cache", None):
        return client
    logger.warning("Нет ключа Claude API (ANTHROPIC_API_KEY): задачи будут сохраняться без оценки")
    return None


def create_agent(settings: AgentSettings, client: anthropic.AsyncAnthropic | None) -> ClaudeAgent:
    return ClaudeAgent(
        client,
        AgentConfig(
            plan_model=settings.agent_plan_model,
            fallback_model=settings.agent_fallback_model,
            plan_effort=settings.agent_plan_effort,
        ),
    )
