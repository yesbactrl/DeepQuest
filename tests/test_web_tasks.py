from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import PlanResult
from deepquest.db.models import Report, TaskStatus, TimeEntry
from deepquest.services import goals
from deepquest.services.proofs import ProofStore
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import FakeAgent, agent_down, draft, verdict

ME = 111
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@dataclass
class Web:
    client: httpx.AsyncClient
    agent: FakeAgent
    proofs_dir: Path
    income: int
    arbitrage: int


@pytest.fixture
async def web(sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path) -> AsyncIterator[Web]:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        income = await goals.create_goal(session, user, "Свой доход", "Не зависеть от зарплаты")
        arbitrage = await goals.create_goal(session, user, "Арбитраж трафика", None, income)
        await session.commit()
        income_id, arbitrage_id = income.id, arbitrage.id

    agent = FakeAgent()

    async def telegram(file_id: str) -> bytes:
        return f"telegram:{file_id}".encode()

    app = create_app(
        sessionmaker, ME, tmp_path / "dist", agent, ProofStore(tmp_path / "proofs"), telegram
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8484",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield Web(client, agent, tmp_path / "proofs", income_id, arbitrage_id)


async def _plan(web: Web, *drafts: object) -> list[dict]:
    web.agent.plans.append(PlanResult(clarify_question=None, tasks=list(drafts)))  # type: ignore[arg-type]
    response = await web.client.post("/api/tasks/plan", json={"text": "мысль"})
    assert response.status_code == 200, response.text
    return response.json()["tasks"]


async def _open_task(web: Web, title: str = "Запустить кампанию", **kwargs: object) -> dict:
    [task] = await _plan(web, draft(title, **kwargs))  # type: ignore[arg-type]
    return (await web.client.post(f"/api/tasks/{task['id']}/save")).json()


async def _rewind(sessionmaker: async_sessionmaker[AsyncSession], minutes: int) -> None:
    async with sessionmaker() as session:
        for entry in await session.scalars(select(TimeEntry)):
            entry.started_at -= timedelta(minutes=minutes)
            if entry.ended_at is not None:
                entry.ended_at -= timedelta(minutes=minutes)
        await session.commit()


# Агент


async def test_thought_becomes_drafts(web: Web) -> None:
    tasks = await _plan(
        web,
        draft("Запустить кампанию", goal_id=web.arbitrage, minutes=180, mult=1.5),
        draft("Записать рилс"),
    )

    assert [t["title"] for t in tasks] == ["Запустить кампанию", "Записать рилс"]
    assert tasks[0]["goal_path"] == "Свой доход → Арбитраж трафика"
    assert (tasks[0]["status"], tasks[0]["estimate_min"], tasks[0]["value_mult"]) == (
        "draft",
        180,
        1.5,
    )
    drafts = (await web.client.get("/api/tasks", params={"status": "draft"})).json()
    assert len(drafts) == 2
    assert (await web.client.get("/api/tasks", params={"status": "open"})).json() == []


async def test_question_then_answer(web: Web) -> None:
    web.agent.plans.append(PlanResult(clarify_question="Что будет результатом?", tasks=[]))
    outcome = (await web.client.post("/api/tasks/plan", json={"text": "поизучать тикток"})).json()
    assert outcome["question"] == "Что будет результатом?"
    [task] = outcome["tasks"]
    assert task["status"] == "clarifying"

    from deepquest.agent.schemas import TasksResult

    web.agent.answers.append(TasksResult(tasks=[draft("Запустить кампанию")]))
    response = await web.client.post(
        f"/api/tasks/{task['id']}/clarify", json={"answer": "запустить"}
    )
    [answered] = response.json()["tasks"]
    assert (answered["id"], answered["status"]) == (task["id"], "draft")


async def test_agent_down_then_manual_estimate(web: Web) -> None:
    web.agent.plans.append(agent_down())
    outcome = (await web.client.post("/api/tasks/plan", json={"text": "сделать сайт"})).json()
    assert outcome["agent_failed"]
    [task] = outcome["tasks"]
    assert task["estimate_min"] is None

    await web.client.post(f"/api/tasks/{task['id']}/save")
    start = await web.client.post(f"/api/tasks/{task['id']}/start")
    assert start.status_code == 409
    assert "оценка" in start.json()["detail"]

    edited = await web.client.patch(
        f"/api/tasks/{task['id']}",
        json={"estimate_min": 90, "value_mult": 1.2, "goal_id": web.income},
    )
    assert edited.status_code == 200
    assert edited.json()["goal_path"] == "Свой доход"
    assert (await web.client.post(f"/api/tasks/{task['id']}/start")).status_code == 200


async def test_revise_with_words(web: Web) -> None:
    task = await _open_task(web, minutes=120)
    web.agent.revisions += [draft("Запустить кампанию", minutes=240), agent_down()]

    revised = (
        await web.client.post(f"/api/tasks/{task['id']}/revise", json={"correction": "на 4 часа"})
    ).json()
    assert (revised["agent_failed"], revised["task"]["estimate_min"]) == (False, 240)
    assert web.agent.calls[-1][1]["correction"] == "на 4 часа"

    failed = (await web.client.post(f"/api/tasks/{task['id']}/revise", json={})).json()
    assert failed["agent_failed"]
    assert failed["task"]["estimate_min"] == 240


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"title": "  "}, "Название"),
        ({"goal_id": 999}, "Нет такой цели"),
        ({"estimate_min": 2}, "Оценка"),
        ({"estimate_min": None}, "Оценка"),
        ({"value_mult": 1.3}, "Множитель"),
        ({"mult_reason": "x" * 201}, "Пояснение"),
    ],
)
async def test_manual_edit_is_validated(web: Web, change: dict, message: str) -> None:
    task = await _open_task(web)

    response = await web.client.patch(f"/api/tasks/{task['id']}", json=change)

    assert response.status_code == 422
    assert message in response.json()["detail"]


# Таймер, отчёт, вердикт


async def test_timer_switches_tasks(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    first = await _open_task(web, "Первая")
    second = await _open_task(web, "Вторая")

    started = (await web.client.post(f"/api/tasks/{first['id']}/start")).json()
    assert started["task"]["running_since"] is not None
    timer = (await web.client.get("/api/timer")).json()
    assert (timer["task_id"], timer["title"], timer["before_min"]) == (first["id"], "Первая", 0)

    switched = (await web.client.post(f"/api/tasks/{second['id']}/start")).json()
    assert switched["paused_task_id"] == first["id"]
    assert (await web.client.get(f"/api/tasks/{first['id']}")).json()["status"] == "open"

    paused = (await web.client.post(f"/api/tasks/{second['id']}/pause")).json()
    assert (paused["status"], paused["running_since"]) == ("open", None)
    assert (await web.client.get("/api/timer")).json() is None


async def test_report_with_screenshot(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    task = await _open_task(web, minutes=120, mult=1.5)
    await web.client.post(f"/api/tasks/{task['id']}/start")
    await _rewind(sessionmaker, 120)
    done = (await web.client.post(f"/api/tasks/{task['id']}/done")).json()
    assert (done["status"], done["spent_min"]) == ("awaiting_report", 120)

    web.agent.validations.append(verdict("accepted", "Запуск виден."))
    response = await web.client.post(
        f"/api/tasks/{task['id']}/report",
        data={"text": "Запустил, кабинет https://ads.example/1"},
        files=[("files", ("screen.png", PNG, "application/octet-stream"))],
    )
    assert response.status_code == 200, response.text
    checked = response.json()

    [report] = web.agent.reports
    assert [(i.media_type, i.data) for i in report.images] == [("image/png", PNG)]
    assert report.links == ("https://ads.example/1",)
    assert (checked["xp_delta"], checked["total_xp"]) == (180, 180)
    detail = checked["task"]
    assert detail["status"] == "done"
    assert detail["validation"]["comment"] == "Запуск виден."
    assert detail["breakdown"]["amount"] == 180
    screenshot, link = detail["report"]["proofs"]
    assert (screenshot["name"], screenshot["is_image"]) == ("screen.png", True)
    assert (await web.client.get(screenshot["url"])).content == PNG
    assert (link["kind"], link["url"], link["is_image"]) == ("link", "https://ads.example/1", False)
    assert detail["can_dispute"]


async def test_report_validation(web: Web) -> None:
    task = await _open_task(web)
    await web.client.post(f"/api/tasks/{task['id']}/done")

    empty = await web.client.post(f"/api/tasks/{task['id']}/report", data={"text": "  "})
    assert empty.status_code == 422
    not_image = await web.client.post(
        f"/api/tasks/{task['id']}/report",
        data={"text": "вот"},
        files=[("files", ("notes.txt", b"hello", "image/png"))],
    )
    assert not_image.status_code == 422
    assert "не картинка" in not_image.json()["detail"]


async def test_agent_down_then_recheck_rereads_screenshot(web: Web) -> None:
    task = await _open_task(web)
    await web.client.post(f"/api/tasks/{task['id']}/done")
    web.agent.validations += [agent_down(), verdict("partial")]

    first = await web.client.post(
        f"/api/tasks/{task['id']}/report",
        data={"text": "сделал"},
        files=[("files", ("s.png", PNG, "image/png"))],
    )
    assert first.json()["agent_failed"]
    assert first.json()["task"]["status"] == "awaiting_report"

    second = (await web.client.post(f"/api/tasks/{task['id']}/recheck")).json()
    assert second["task"]["validation"]["verdict"] == "partial"
    assert [i.data for i in web.agent.reports[-1].images] == [PNG]


async def test_dispute_once(web: Web, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    task = await _open_task(web, minutes=60, mult=1.0)
    await web.client.post(f"/api/tasks/{task['id']}/start")
    await _rewind(sessionmaker, 60)
    await web.client.post(f"/api/tasks/{task['id']}/done")
    web.agent.validations += [verdict("rejected"), verdict("accepted")]
    rejected = (
        await web.client.post(f"/api/tasks/{task['id']}/report", data={"text": "сделал"})
    ).json()
    assert rejected["task"]["status"] == "rejected"

    disputed = (
        await web.client.post(f"/api/tasks/{task['id']}/dispute", json={"argument": "вот факты"})
    ).json()

    assert web.agent.reports[-1].dispute == "вот факты"
    # Без пруфа: 60 × 1.0 × 1.0 × 0.8
    assert (disputed["xp_delta"], disputed["task"]["status"]) == (48, "done")
    assert not disputed["task"]["can_dispute"]
    again = await web.client.post(f"/api/tasks/{task['id']}/dispute", json={"argument": "ещё"})
    assert again.status_code == 409


async def test_telegram_screenshot_is_shown_in_web(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    task = await _open_task(web)
    await web.client.post(f"/api/tasks/{task['id']}/done")
    async with sessionmaker() as session:
        session.add(
            Report(
                task_id=task["id"],
                text="из бота",
                proofs=[{"kind": "photo", "file_id": "abc", "mime_type": "image/jpeg"}],
                honor_mode=False,
            )
        )
        await session.commit()

    detail = (await web.client.get(f"/api/tasks/{task['id']}")).json()
    [proof] = detail["report"]["proofs"]

    assert (await web.client.get(proof["url"])).content == b"telegram:abc"


async def test_goal_filter_includes_directions(web: Web) -> None:
    await _open_task(web, "По цели", goal_id=web.income)
    await _open_task(web, "По направлению", goal_id=web.arbitrage)
    await _open_task(web, "Без цели")

    titles = {
        t["title"]
        for t in (await web.client.get("/api/tasks", params={"goal_id": web.income})).json()
    }

    assert titles == {"По цели", "По направлению"}


async def test_upload_needs_csrf_header(web: Web) -> None:
    task = await _open_task(web)
    response = await web.client.post(
        f"/api/tasks/{task['id']}/report", data={"text": "x"}, headers={"X-DeepQuest": ""}
    )
    assert response.status_code == 403
    status = (await web.client.get(f"/api/tasks/{task['id']}")).json()["status"]
    assert status == TaskStatus.OPEN.value


# Время без таймера


async def _entries(sessionmaker: async_sessionmaker[AsyncSession]) -> list[tuple[int, str | None]]:
    async with sessionmaker() as session:
        entries = await session.scalars(select(TimeEntry).order_by(TimeEntry.started_at))
        return [
            (int((e.ended_at - e.started_at).total_seconds() // 60), e.stop_reason)
            for e in entries
            if e.ended_at is not None
        ]


async def test_report_without_timer_counts_estimate(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    task = await _open_task(web, minutes=60, mult=1.5)
    web.agent.validations.append(verdict())
    await web.client.post(f"/api/tasks/{task['id']}/done")

    result = (
        await web.client.post(f"/api/tasks/{task['id']}/report", data={"text": "https://x.io"})
    ).json()

    assert web.agent.reports[0].actual_min == 60
    assert result["xp_delta"] == 90
    assert await _entries(sessionmaker) == [(60, "logged")]


async def test_report_with_spent_time(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    task = await _open_task(web, minutes=60, mult=1.0)
    web.agent.validations.append(verdict())
    await web.client.post(f"/api/tasks/{task['id']}/start")
    await _rewind(sessionmaker, 30)
    await web.client.post(f"/api/tasks/{task['id']}/done")

    # По таймеру 30 минут, а на деле ушло 45: дописываем недостающие 15.
    result = (
        await web.client.post(
            f"/api/tasks/{task['id']}/report", data={"text": "https://x.io", "spent_min": "45"}
        )
    ).json()

    assert web.agent.reports[0].actual_min == 45
    assert result["xp_delta"] == 45
    assert await _entries(sessionmaker) == [(30, "done"), (15, "logged")]


async def test_change_time_recounts_xp(
    web: Web, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    task = await _open_task(web, minutes=60, mult=1.0)
    web.agent.validations.append(verdict("partial"))
    await web.client.post(f"/api/tasks/{task['id']}/done")
    await web.client.post(f"/api/tasks/{task['id']}/report", data={"text": "Сделал"})
    # 60 мин × 0.7 × 0.8 = 34

    more = (await web.client.post(f"/api/tasks/{task['id']}/time", json={"spent_min": 90})).json()
    # 90 × 0.7 × 0.8 = 50: поправка +16, агента заново не спрашиваем.
    assert (more["xp_delta"], more["task"]["xp"], more["task"]["spent_min"]) == (16, 50, 90)
    assert more["task"]["breakdown"]["actual_min"] == 90
    assert len(web.agent.reports) == 1

    less = (await web.client.post(f"/api/tasks/{task['id']}/time", json={"spent_min": 20})).json()
    assert (less["xp_delta"], less["task"]["xp"]) == (-39, 11)
    assert await _entries(sessionmaker) == [(20, "logged")]


async def test_change_time_needs_done_task(web: Web) -> None:
    task = await _open_task(web)
    response = await web.client.post(f"/api/tasks/{task['id']}/time", json={"spent_min": 30})
    assert response.status_code == 409
    await web.client.post(f"/api/tasks/{task['id']}/start")
    response = await web.client.post(f"/api/tasks/{task['id']}/time", json={"spent_min": 30})
    assert response.status_code == 409
    bad = await web.client.post(f"/api/tasks/{task['id']}/time", json={"spent_min": 0})
    assert bad.status_code == 422
