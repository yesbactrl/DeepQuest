"""SubscriptionAgent против подставного `claude`: аргументы, ввод, разбор потока, ошибки."""

import json
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from deepquest.agent.api import ApiAgent
from deepquest.agent.base import AgentCallLog, AgentConfig, AgentError, AgentResult, FallbackAgent
from deepquest.agent.schemas import (
    CurrentTask,
    GoalContext,
    PlanResult,
    ProofImage,
    ReportContext,
)
from deepquest.agent.setup import build_agent
from deepquest.agent.subscription import ClaudeCodeConfig, SubscriptionAgent
from deepquest.config import AgentSettings

GOALS = [GoalContext(id=1, title="Свой доход", why="Не зависеть от зарплаты")]
PLAN = {
    "clarify_question": None,
    "tasks": [
        {
            "title": "Запустить кампанию",
            "expected_result": "Кампания запущена",
            "goal_id": 1,
            "estimate_min": 120,
            "value_mult": 1.5,
            "mult_reason": "реальный шаг",
        }
    ],
}

FAKE_CLAUDE = """#!{python}
import json, os, sys, time
from pathlib import Path

here = Path(__file__).parent
queue = json.loads((here / "responses.json").read_text())
response = queue.pop(0)
(here / "responses.json").write_text(json.dumps(queue))
call = {{
    "args": sys.argv[1:],
    "stdin": sys.stdin.read(),
    "cwd": os.getcwd(),
    "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
}}
with (here / "calls.jsonl").open("a") as f:
    f.write(json.dumps(call) + "\\n")
time.sleep(response.get("sleep", 0))
print(json.dumps({{"type": "system", "subtype": "init"}}))
print("not json")
if "result" in response:
    print(json.dumps({{"type": "result", **response["result"]}}))
sys.stderr.write(response.get("stderr", ""))
sys.exit(response.get("exit", 0))
"""


def _success(structured: dict[str, Any], model: str = "claude-haiku-5-5") -> dict[str, Any]:
    return {
        "result": {
            "subtype": "success",
            "is_error": False,
            "stop_reason": "tool_use",
            "session_id": "s-1",
            "structured_output": structured,
            "total_cost_usd": 0.0004,
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 1450,
                "cache_read_input_tokens": 0,
                "output_tokens": 200,
            },
            "modelUsage": {model: {}},
        }
    }


class FakeClaudeCode:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "claude"
        self.path.write_text(FAKE_CLAUDE.format(python=sys.executable))
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)
        self.workdir = root / "workdir"
        self.respond()

    def respond(self, *responses: dict[str, Any]) -> None:
        (self.root / "responses.json").write_text(json.dumps(list(responses)))

    @property
    def calls(self) -> list[dict[str, Any]]:
        log = self.root / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def agent(self, timeout_s: float = 30) -> SubscriptionAgent:
        cli = ClaudeCodeConfig(executable=str(self.path), workdir=self.workdir, timeout_s=timeout_s)
        return SubscriptionAgent(cli, AgentConfig())


@pytest.fixture
def claude(tmp_path: Path) -> FakeClaudeCode:
    return FakeClaudeCode(tmp_path)


def _arg(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


async def test_plan_task_runs_isolated_claude_code(
    claude: FakeClaudeCode, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    claude.respond(_success(PLAN))

    result = await claude.agent().plan_task("запустить кампанию в тиктоке", GOALS)

    assert result.output == PlanResult.model_validate(PLAN)
    [call] = claude.calls
    args = call["args"]
    assert "--safe-mode" in args and "--strict-mcp-config" in args
    assert _arg(args, "--tools") == ""
    assert _arg(args, "--model") == "claude-haiku-5-5"
    assert _arg(args, "--effort") == "medium"
    assert _arg(args, "--system-prompt-file").endswith("prompts/plan_task.md")
    assert "clarify_question" in json.loads(_arg(args, "--json-schema"))["properties"]
    # Ключ API не уходит в Claude Code, иначе запрос оплатился бы по API.
    assert call["has_api_key"] is False
    assert Path(call["cwd"]).resolve() == claude.workdir.resolve()
    message = json.loads(call["stdin"])
    assert message["type"] == "user"
    assert "id=1: цель «Свой доход»" in message["message"]["content"][-1]["text"]
    [log] = result.calls
    assert (log.tokens_in, log.tokens_out, log.error) == (1452, 200, None)
    assert log.response is not None and log.response["models"] == ["claude-haiku-5-5"]


async def test_screenshot_goes_into_stream_json(claude: FakeClaudeCode) -> None:
    claude.respond(
        _success({"verdict": "accepted", "reason": "видно", "comment": "ок"}, "claude-opus-5-5")
    )
    report = ReportContext(
        task=CurrentTask("Запустить кампанию", "Запущена", 1, 120, 1.5, "реальный шаг"),
        goal="Свой доход",
        goal_why=None,
        actual_min=90,
        report_text="Запустил",
        links=(),
        images=(ProofImage("image/png", b"png"),),
        other_files=0,
        honor_mode=False,
    )

    result = await claude.agent().validate_report(report)

    assert result.output.verdict == "accepted"
    [call] = claude.calls
    assert _arg(call["args"], "--model") == "claude-opus-5-5"
    image, text = json.loads(call["stdin"])["message"]["content"]
    assert (image["type"], image["source"]["media_type"]) == ("image", "image/png")
    assert "Фактическое время по таймеру: 90 мин" in text["text"]


async def test_refusal_moves_to_next_model(claude: FakeClaudeCode) -> None:
    refusal = {"result": {"subtype": "success", "is_error": False, "stop_reason": "refusal"}}
    claude.respond(refusal, _success(PLAN, "claude-opus-5-5"))

    result = await claude.agent().plan_task("текст", GOALS)

    assert [_arg(c["args"], "--model") for c in claude.calls] == [
        "claude-haiku-5-5",
        "claude-opus-5-5",
    ]
    assert [c.error for c in result.calls] == ["refusal", None]


async def test_usage_limit_is_an_agent_error(claude: FakeClaudeCode) -> None:
    claude.respond(
        {
            "result": {
                "subtype": "error_during_execution",
                "is_error": True,
                "result": "Claude usage limit reached",
            }
        }
    )

    with pytest.raises(AgentError, match="usage limit reached"):
        await claude.agent().plan_task("текст", GOALS)
    assert len(claude.calls) == 1  # другая модель лимит не обойдёт


async def test_crash_without_result_reports_stderr(claude: FakeClaudeCode) -> None:
    claude.respond({"exit": 1, "stderr": "Not logged in"})

    with pytest.raises(AgentError, match="Not logged in"):
        await claude.agent().plan_task("текст", GOALS)


async def test_timeout_kills_claude_code(claude: FakeClaudeCode) -> None:
    claude.respond({"sleep": 5, **_success(PLAN)})

    with pytest.raises(AgentError, match="timed out"):
        await claude.agent(timeout_s=0.5).plan_task("текст", GOALS)


async def test_missing_cli_fails_without_running(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="not found"):
        await SubscriptionAgent(None).plan_task("текст", GOALS)


# Запасной агент и выбор бэкенда


class _StubAgent:
    def __init__(self, outcome: PlanResult | AgentError) -> None:
        self.outcome = outcome

    async def plan_task(self, text: str, goals: object) -> AgentResult[PlanResult]:
        if isinstance(self.outcome, AgentError):
            raise self.outcome
        log = AgentCallLog(kind="plan_task", prompt_version="t", model="stub", request={})
        return AgentResult(self.outcome, [log])


async def test_fallback_agent_keeps_both_logs() -> None:
    failed = AgentCallLog(kind="plan_task", prompt_version="t", model="sub", request={}, error="x")
    agent = FallbackAgent(
        _StubAgent(AgentError("limit", [failed])),  # type: ignore[arg-type]
        _StubAgent(PlanResult.model_validate(PLAN)),  # type: ignore[arg-type]
    )

    result = await agent.plan_task("текст", GOALS)

    assert [c.model for c in result.calls] == ["sub", "stub"]


def _settings(**values: Any) -> AgentSettings:
    return AgentSettings(_env_file=None, **values)  # type: ignore[call-arg]


def test_build_agent_picks_backend(
    claude: FakeClaudeCode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = {"claude_code_path": str(claude.path), "agent_workdir": tmp_path / "w"}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert isinstance(build_agent(_settings(**common)).agent, SubscriptionAgent)
    assert isinstance(
        build_agent(
            _settings(**common, agent_backend="api", anthropic_api_key=SecretStr("k"))
        ).agent,
        ApiAgent,
    )
    with_fallback = build_agent(
        _settings(**common, agent_api_fallback=True, anthropic_api_key=SecretStr("k"))
    )
    assert isinstance(with_fallback.agent, FallbackAgent)
    # Включённый запасной вариант без ключа — просто подписка.
    assert isinstance(
        build_agent(_settings(**common, agent_api_fallback=True)).agent, SubscriptionAgent
    )
