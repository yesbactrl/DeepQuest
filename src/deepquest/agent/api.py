"""Агент через Claude API: платные запросы по ключу ANTHROPIC_API_KEY."""

import time
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from deepquest.agent.base import (
    AgentCallLog,
    AgentConfig,
    CallFailed,
    ModelRefused,
    PromptedAgent,
    Route,
)

# Отказ модели по политике безопасности сервер повторяет на подходящей модели сам.
# У Haiku такого fallback нет (отказ останется отказом) — тогда базовый класс
# пробует следующую модель маршрута.
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ApiAgent(PromptedAgent):
    def __init__(
        self, client: anthropic.AsyncAnthropic | None, config: AgentConfig | None = None
    ) -> None:
        super().__init__(config)
        self._client = client

    async def _call[T: BaseModel](
        self,
        route: Route,
        model: str,
        content: list[dict[str, Any]],
        output_model: type[T],
        log: AgentCallLog,
    ) -> T:
        if self._client is None:
            log.error = "Claude API client is not configured"
            raise CallFailed(log.error)

        started = time.monotonic()
        try:
            response = await self._client.beta.messages.create(
                model=model,
                max_tokens=self._config.max_tokens,
                system=route.prompt.text,
                messages=[{"role": "user", "content": content}],  # type: ignore[typeddict-item]
                output_config={
                    "effort": route.effort,  # type: ignore[typeddict-item]
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic.transform_schema(output_model),
                    },
                },
                fallbacks="default",
                betas=[SERVER_FALLBACK_BETA],
            )
        except anthropic.APIStatusError as exc:
            log.latency_ms = round((time.monotonic() - started) * 1000)
            log.error = f"HTTP {exc.status_code}: {exc.message}"
            raise CallFailed(log.error) from exc
        except anthropic.APIConnectionError as exc:
            log.latency_ms = round((time.monotonic() - started) * 1000)
            log.error = f"{type(exc).__name__}: {exc}"
            raise CallFailed(log.error) from exc
        except anthropic.AnthropicError as exc:
            log.error = f"{type(exc).__name__}: {exc}"
            raise CallFailed(log.error) from exc

        log.latency_ms = round((time.monotonic() - started) * 1000)
        # Ответ может начинаться с блоков thinking: берём только текст.
        text = "".join(block.text for block in response.content if block.type == "text")
        log.stop_reason = response.stop_reason
        log.tokens_in = response.usage.input_tokens
        log.tokens_out = response.usage.output_tokens
        # Если сработал серверный fallback, ответила другая модель — она в response.model.
        log.response = {"id": response.id, "model": response.model, "text": text}

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            log.error = f"refusal: {category}"
            raise ModelRefused(log.error)
        if response.stop_reason == "max_tokens":
            log.error = "Output hit max_tokens"
            raise CallFailed(log.error)
        try:
            return output_model.model_validate_json(text)
        except ValidationError as exc:
            log.error = f"Invalid output: {exc}"
            raise CallFailed(log.error) from exc
