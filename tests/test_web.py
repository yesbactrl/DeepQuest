from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.config import Settings
from deepquest.db.models import TaskStatus, TimeEntry, ValidationVerdict
from deepquest.services import goals, tasks, xp
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import BotHarness, FakeAgent

ME = 111
WHY = "Не зависеть от зарплаты"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>")
    (root / "assets" / "app.js").write_text("console.log('deepquest')")
    (root / "favicon.svg").write_text("<svg/>")
    return root


@pytest.fixture
def app(sessionmaker: async_sessionmaker[AsyncSession], dist: Path) -> FastAPI:
    return create_app(sessionmaker, ME, dist, FakeAgent(), ProofStore(dist.parent / "proofs"))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1:8484",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


async def _create(client: httpx.AsyncClient, **body: object) -> httpx.Response:
    return await client.post("/api/goals", json=body)


# Защита


async def test_foreign_host_is_rejected(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://evil.example"
    ) as stranger:
        response = await stranger.get("/api/health")
    assert response.status_code == 400


async def test_tailscale_host_is_allowed_when_named(
    sessionmaker: async_sessionmaker[AsyncSession], dist: Path
) -> None:
    mac = "mac.tail1234.ts.net"
    app = create_app(
        sessionmaker, ME, dist, FakeAgent(), ProofStore(dist.parent / "proofs"), extra_hosts=[mac]
    )
    for host, status in ((mac, 200), ("other.tail1234.ts.net", 400)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=f"https://{host}"
        ) as phone:
            assert (await phone.get("/api/goals")).status_code == status


def test_web_hosts_setting_is_split() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        bot_enabled=False,
        web_hosts=" Mac.tail1234.ts.net , ",  # type: ignore[arg-type]
    )
    assert settings.web_hosts == ["mac.tail1234.ts.net"]


async def test_changes_need_csrf_header(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8484"
    ) as bare:
        assert (await bare.get("/api/goals")).status_code == 200
        response = await bare.post("/api/goals", json={"title": "Доход", "why": WHY})
    assert response.status_code == 403


async def test_web_needs_bot_owner(
    sessionmaker: async_sessionmaker[AsyncSession], dist: Path
) -> None:
    app = create_app(sessionmaker, None, dist, FakeAgent(), ProofStore(dist.parent / "proofs"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/api/goals")
    assert response.status_code == 503
    assert "ALLOWED_TELEGRAM_IDS" in response.json()["detail"]


# Цели


async def test_goal_crud(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/goals")).json() == []

    response = await _create(client, title="Свой доход")
    assert response.status_code == 422
    assert "зачем" in response.json()["detail"]

    [goal] = (await _create(client, title="  Свой   доход ", why=WHY)).json()
    assert (goal["title"], goal["why"], goal["directions"]) == ("Свой доход", WHY, [])

    [goal] = (await _create(client, title="Арбитраж трафика", parent_id=goal["id"])).json()
    [direction] = goal["directions"]
    assert (direction["title"], direction["why"]) == ("Арбитраж трафика", None)

    nested = await _create(client, title="TikTok", parent_id=direction["id"])
    assert nested.status_code == 409

    [goal] = (await client.patch(f"/api/goals/{goal['id']}", json={"title": "Доход"})).json()
    assert goal["title"] == "Доход"
    cleared = await client.patch(f"/api/goals/{goal['id']}", json={"why": "  "})
    assert cleared.status_code == 422  # у цели «зачем» обязательно
    [goal] = (
        await client.patch(f"/api/goals/{direction['id']}", json={"why": "Первый доход"})
    ).json()
    assert goal["directions"][0]["why"] == "Первый доход"

    assert (await client.post(f"/api/goals/{goal['id']}/archive")).json() == []
    assert (await client.patch(f"/api/goals/{goal['id']}", json={"title": "x"})).status_code == 404


async def test_title_validation(client: httpx.AsyncClient) -> None:
    response = await _create(client, title="x" * (goals.MAX_TITLE_LEN + 1), why=WHY)
    assert response.status_code == 422
    assert "Название" in response.json()["detail"]


async def test_goal_stats_include_directions(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    now = datetime.now(UTC)
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        income = await goals.create_goal(session, user, "Свой доход", WHY)
        arbitrage = await goals.create_goal(session, user, "Арбитраж", None, income)
        health = await goals.create_goal(session, user, "Здоровье", "Энергия")
        health.created_at = now - timedelta(days=10)

        fields = TaskFields("Запустить кампанию", None, arbitrage.id, 120, 1.5, None)
        task = await tasks.create_draft(session, user, fields, "текст", None)
        task.status = TaskStatus.DONE
        session.add_all(
            [
                TimeEntry(
                    user_id=user.id,
                    task_id=task.id,
                    started_at=now - timedelta(minutes=90),
                    ended_at=now - timedelta(minutes=30),
                ),
                TimeEntry(user_id=user.id, task_id=task.id, started_at=now - timedelta(minutes=20)),
            ]
        )
        breakdown = xp.compute_task_xp(
            actual_min=80,
            estimate_min=120,
            value_mult=1.5,
            verdict=ValidationVerdict.ACCEPTED,
            honor_mode=False,
        )
        await xp.record_task_xp(session, user, task, breakdown, now)
        await session.commit()

    income_out, health_out = (await client.get("/api/goals")).json()

    # Время цели — засчитанные минуты (оценка 120), а не таймер (80 и ещё идёт).
    assert income_out["stats"]["minutes"] == 120
    # XP — от оценки, не от таймера: 120 мин × 1.5 × 1.1 за пруф
    assert income_out["stats"]["xp"] == 198
    assert income_out["stats"]["done_tasks"] == 1
    assert income_out["stats"]["idle_days"] == 0
    assert income_out["directions"][0]["stats"]["minutes"] == 120
    assert health_out["stats"] == {
        "minutes": 0,
        "xp": 0,
        "done_tasks": 0,
        "last_activity_at": None,
        "idle_days": 10,
    }


async def test_bot_and_web_share_goals(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _create(client, title="Здоровье", why="Энергия")

    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await harness.send(ME, "/goals")

    assert "1. <b>Здоровье</b>" in harness.last_text


# Фронтенд


async def test_frontend_is_served_with_spa_fallback(client: httpx.AsyncClient) -> None:
    index = await client.get("/")
    assert index.status_code == 200 and "id=root" in index.text
    assert "id=root" in (await client.get("/goals")).text
    assert (await client.get("/assets/app.js")).text == "console.log('deepquest')"
    assert (await client.get("/favicon.svg")).text == "<svg/>"


async def test_unknown_api_is_404_not_index(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["detail"] == "Нет такого адреса API"


async def test_missing_build_explains_what_to_do(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app = create_app(sessionmaker, ME, tmp_path / "no-dist", FakeAgent(), ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/goals")
    assert response.status_code == 503
    assert "npm run build" in response.text
