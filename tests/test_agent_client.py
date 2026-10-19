"""ApiAgent против фейкового клиента Anthropic: разбор ответа, отказы, ошибки."""

import base64
import json
from typing import Any

import anthropic
import httpx2
import pytest
from anthropic.types import Message

from deepquest.agent.api import ApiAgent
from deepquest.agent.base import AgentConfig, AgentError, Prompt, render_goals
from deepquest.agent.schemas import CurrentTask, GoalContext, ProofImage, ReportContext

GOALS = [
    GoalContext(
        id=1,
        title="Свой доход",
        why="Не зависеть от зарплаты",
        directions=(GoalContext(id=2, title="Арбитраж трафика", why=None),),
    )
]

PLAN_JSON = json.dumps(
    {
        "clarify_question": None,
        "tasks": [
            {
                "title": "Запустить тестовую кампанию в TikTok с бюджетом $20",
                "expected_result": "Кампания запущена, есть первые цифры по кликам",
                "goal_id": 2,
                "estimate_min": 180,
                "value_mult": 1.5,
                "mult_reason": "реальный шаг, некомфортно",
            }
        ],
    },
    ensure_ascii=False,
)


def _message(text: str, stop_reason: str = "end_turn", model: str = "claude-haiku-5-5") -> Message:
    return Message.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            # Ответ может начинаться с thinking: агент должен брать только text.
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": text},
            ],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300},
        }
    )


class FakeMessages:
    def __init__(self, responses: list[Message | Exception]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeBeta:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


class FakeClaude:
    def __init__(self, *responses: Message | Exception) -> None:
        self.messages = FakeMessages(list(responses))
        self.beta = FakeBeta(self.messages)


def _agent(client: FakeClaude | None) -> ApiAgent:
    return ApiAgent(client, AgentConfig())  # type: ignore[arg-type]


async def test_plan_task_parses_structured_output() -> None:
    client = FakeClaude(_message(PLAN_JSON))

    result = await _agent(client).plan_task("надо попробовать залить связку на тикток", GOALS)

    [task] = result.output.tasks
    assert (task.goal_id, task.estimate_min, task.value_mult) == (2, 180, 1.5)
    [request] = client.messages.requests
    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == Prompt.load("plan_task").text
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"]["type"] == "json_schema"
    [text_block] = request["messages"][0]["content"]
    assert "id=2: направление «Арбитраж трафика»" in text_block["text"]
    [call] = result.calls
    assert (call.kind, call.tokens_in, call.tokens_out, call.error) == (
        "plan_task",
        1200,
        300,
        None,
    )


async def test_refusal_falls_back_to_opus() -> None:
    client = FakeClaude(
        _message("", stop_reason="refusal"),
        _message(PLAN_JSON, model="claude-opus-5-5"),
    )

    result = await _agent(client).plan_task("текст", GOALS)

    assert [r["model"] for r in client.messages.requests] == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert [c.error for c in result.calls] == ["refusal: None", None]
    assert result.output.tasks


async def test_every_model_refusing_is_an_error() -> None:
    client = FakeClaude(_message("", "refusal"), _message("", "refusal"))

    with pytest.raises(AgentError) as error:
        await _agent(client).plan_task("текст", GOALS)

    assert len(error.value.calls) == 2


async def test_connection_error_is_reported_with_log() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    client = FakeClaude(anthropic.APIConnectionError(request=request))

    with pytest.raises(AgentError) as error:
        await _agent(client).plan_task("текст", GOALS)

    [call] = error.value.calls
    assert call.error is not None and call.error.startswith("APIConnectionError")


async def test_invalid_json_is_an_error() -> None:
    client = FakeClaude(_message("{not json"))

    with pytest.raises(AgentError, match="Invalid output"):
        await _agent(client).plan_task("текст", GOALS)


async def test_missing_client_fails_without_request() -> None:
    with pytest.raises(AgentError, match="not configured"):
        await _agent(None).plan_task("текст", GOALS)


def test_render_goals_lists_directions_and_missing_why() -> None:
    rendered = render_goals(GOALS)
    assert "id=1: цель «Свой доход». Зачем: Не зависеть от зарплаты" in rendered
    assert "  - id=2: направление «Арбитраж трафика». Зачем: не указано" in rendered
    assert "Целей пока нет" in render_goals([])


def test_prompt_version_tracks_text() -> None:
    prompt = Prompt.load("plan_task")
    assert prompt.version == Prompt("plan_task", prompt.text).version
    assert prompt.version != Prompt("plan_task", prompt.text + " ").version


async def test_validate_report_sends_screenshot_first_with_server_fallback() -> None:
    answer = json.dumps({"verdict": "accepted", "reason": "Запуск виден", "comment": "Отлично"})
    client = FakeClaude(_message(answer, model="claude-opus-5-5"))
    report = ReportContext(
        task=CurrentTask(
            title="Запустить кампанию",
            expected_result="Кампания запущена",
            goal_id=2,
            estimate_min=180,
            value_mult=1.5,
            mult_reason="реальный шаг",
        ),
        goal="Свой доход → Арбитраж трафика",
        goal_why="Не зависеть от зарплаты",
        actual_min=120,
        report_text="Запустил на $20",
        links=("https://ads.example/1",),
        images=(ProofImage("image/png", b"img"),),
        other_files=0,
        honor_mode=False,
    )

    result = await _agent(client).validate_report(report)

    assert result.output.verdict == "accepted"
    [request] = client.messages.requests
    assert request["model"] == "claude-opus-5-5"
    assert (request["fallbacks"], request["betas"]) == (
        "default",
        ["server-side-fallback-2026-07-01"],
    )
    image, text = request["messages"][0]["content"]
    assert image["type"] == "image"
    assert base64.b64decode(image["source"]["data"]) == b"img"
    assert "Фактическое время по таймеру: 120 мин (оценка: 180 мин)" in text["text"]
    assert "Ссылки: https://ads.example/1" in text["text"]
    # В журнал вызовов картинка не попадает, только их число.
    [call] = result.calls
    assert call.request["images"] == 1
    assert image["source"]["data"] not in json.dumps(call.request)
