from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.agent.schemas import DiaryAnalysis, DiarySphereNote
from deepquest.bot import texts
from deepquest.db.models import DiaryEntry, DiaryStatus, TimeEntry, User, XpEvent, XpKind
from deepquest.services import diary, goals, tasks
from deepquest.services.days import season_of
from deepquest.services.proofs import ProofStore
from deepquest.services.tasks import TaskFields
from deepquest.services.users import get_or_create_user
from deepquest.web.app import create_app
from tests.conftest import BotHarness, FakeAgent, FakeTranscriber, agent_down

ME = 111
# Вторник 20 октября 2026, 08:15 по Москве.
MORNING = datetime(2026, 10, 20, 5, 15, tzinfo=UTC)


def analysis(
    mood: int | None = 2,
    energy: int | None = 2,
    drive: int | None = 1,
    emotions: tuple[str, ...] = ("апатия",),
    factors: tuple[str, ...] = ("плохой сон",),
    summary: str = "Проснулся разбитым, ничего не хочется",
) -> DiaryAnalysis:
    return DiaryAnalysis(
        mood=mood,  # type: ignore[arg-type]
        energy=energy,  # type: ignore[arg-type]
        drive=drive,  # type: ignore[arg-type]
        emotions=list(emotions),
        factors=list(factors),
        summary=summary,
    )


@pytest.fixture
async def user_id(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as session:
        user = await get_or_create_user(session, ME)
        user.tz = "Europe/Moscow"
        await session.commit()
        return user.id


async def _user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    assert user is not None
    return user


# Сервис


@pytest.mark.parametrize(
    ("utc_hour", "part"),
    [(1, "morning"), (8, "morning"), (9, "day"), (14, "day"), (15, "evening"), (0, "evening")],
)
def test_part_of_day(utc_hour: int, part: str) -> None:
    # Москва = UTC+3, граница дня 04:00: 04–12 утро, 12–18 день, остальное вечер.
    user = User(telegram_id=1, tz="Europe/Moscow", day_boundary_hour=4)
    moment = datetime(2026, 10, 20, utc_hour, tzinfo=UTC)
    assert diary.part_of_day(user, moment) == part


def test_tags_are_cleaned() -> None:
    assert diary.clean_tags(["  Плохой   сон ", "плохой сон", "", "Тренировка"]) == [
        "плохой сон",
        "тренировка",
    ]


async def test_entry_is_analyzed_with_known_tags(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary += [
        analysis(factors=("Плохой сон", "дедлайн")),
        analysis(mood=4, energy=4, drive=4, emotions=("радость",), factors=("тренировка",)),
    ]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        first = await diary.add_entry(session, agent, user, "Проснулся разбитым", MORNING)
        await session.commit()
        later = MORNING + timedelta(hours=10)
        second = await diary.add_entry(session, agent, user, "После зала отлично", later)
        await session.commit()

    entry = first.entry
    assert (entry.mood, entry.energy, entry.drive) == (2, 2, 1)
    assert entry.factors == ["плохой сон", "дедлайн"]
    assert (entry.status, entry.part_of_day, entry.logical_date.day) == (
        DiaryStatus.DONE,
        "morning",
        20,
    )
    assert agent.diary_entries[0].written_at == "вторник, 20 октября, 08:15 (утро)"
    # Второй записи агент подсказывает прошлые формулировки, чтобы статистика не рассыпалась.
    assert agent.diary_entries[1].known_factors[:2] == ("плохой сон", "дедлайн")
    assert agent.diary_entries[1].known_emotions == ("апатия",)
    assert second.entry.part_of_day == "evening"


async def test_agent_down_then_reanalyze(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary += [agent_down(), analysis()]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        outcome = await diary.add_entry(session, agent, user, "Ничего не хочется", MORNING)
        assert outcome.agent_failed
        assert (outcome.entry.status, outcome.entry.mood) == (DiaryStatus.FAILED, None)

        retried = await diary.reanalyze(session, agent, user, outcome.entry)

    assert not retried.agent_failed
    assert (retried.entry.status, retried.entry.drive) == (DiaryStatus.DONE, 1)


async def test_private_entry_skips_agent(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        outcome = await diary.add_entry(
            session, agent, user, "Только для себя", MORNING, analyze=False
        )

    assert outcome.entry.status == DiaryStatus.PRIVATE
    assert agent.calls == []


async def test_manual_scores_survive_reanalysis(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary += [analysis(), analysis(mood=5, summary="Новая суть")]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        entry = (await diary.add_entry(session, agent, user, "Так себе утро", MORNING)).entry
        await diary.edit_entry(
            session, user, entry, diary.EntryEdit(mood=3, factors=["Дождь"], energy=0)
        )

        await diary.reanalyze(session, agent, user, entry)

    assert (entry.mood, entry.energy, entry.factors, entry.edited) == (3, None, ["дождь"], True)
    assert entry.summary == "Новая суть"


async def test_days_show_averages_and_work(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary += [analysis(mood=2, energy=None), analysis(mood=4, energy=3)]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        await diary.add_entry(session, agent, user, "Утро", MORNING)
        await diary.add_entry(session, agent, user, "Вечер", MORNING + timedelta(hours=12))
        task = await tasks.create_draft(
            session, user, TaskFields("Работа", None, None, 60, 1.0, None), "т", None
        )
        start = MORNING + timedelta(hours=2)
        session.add(
            TimeEntry(
                user_id=user.id,
                task_id=task.id,
                started_at=start,
                ended_at=start + timedelta(minutes=90),
            )
        )
        day = MORNING.date()
        session.add(
            XpEvent(
                user_id=user.id,
                task_id=task.id,
                kind=XpKind.TASK,
                amount=90,
                breakdown={},
                logical_date=day,
                season=season_of(day),
            )
        )
        await session.flush()

        [today] = await diary.list_days(session, user, MORNING + timedelta(hours=13), days=7)

    assert [e.text for e in today.entries] == ["Вечер", "Утро"]
    assert (today.mood, today.energy, today.drive) == (3.0, 3.0, 1.0)
    # XP дня: 90 за задачу и по 15 за каждую из двух записей.
    assert (today.focus_min, today.xp) == (90, 120)


# Веб


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent()


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], tmp_path: Path, agent: FakeAgent, user_id: int
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(sessionmaker, ME, tmp_path / "dist", agent, ProofStore(tmp_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-DeepQuest": "1"},
    ) as client:
        yield client


async def test_diary_api(client: httpx.AsyncClient, agent: FakeAgent) -> None:
    agent.diary.append(analysis())

    created = await client.post("/api/diary", json={"text": "Проснулся разбитым"})
    assert created.status_code == 201
    entry = created.json()["entry"]
    assert (entry["mood"], entry["factors"], entry["status"]) == (2, ["плохой сон"], "done")

    edited = await client.patch(f"/api/diary/{entry['id']}", json={"mood": 3, "drive": 0})
    assert (edited.json()["mood"], edited.json()["drive"], edited.json()["edited"]) == (
        3,
        None,
        True,
    )

    listed = (await client.get("/api/diary")).json()
    [day] = listed["days"]
    assert (day["mood"], day["entries"][0]["id"], listed["norm_min"]) == (3.0, entry["id"], 60)

    assert (await client.delete(f"/api/diary/{entry['id']}")).status_code == 204
    assert (await client.get("/api/diary")).json()["days"] == []
    assert (await client.patch(f"/api/diary/{entry['id']}", json={"mood": 1})).status_code == 404


async def test_diary_api_private_and_reanalyze(client: httpx.AsyncClient, agent: FakeAgent) -> None:
    created = (await client.post("/api/diary", json={"text": "Для себя", "analyze": False})).json()
    assert (created["entry"]["status"], created["agent_failed"]) == ("private", False)
    assert agent.calls == []

    agent.diary.append(analysis())
    analyzed = (await client.post(f"/api/diary/{created['entry']['id']}/analyze")).json()
    assert analyzed["entry"]["status"] == "done"


async def test_diary_api_validation(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/diary", json={"text": "   "})).status_code == 422
    assert (await client.post("/api/diary", json={"text": ""})).status_code == 422
    bad = await client.patch("/api/diary/1", json={"mood": 7})
    assert bad.status_code == 422


# Бот


async def _entries(sessionmaker: async_sessionmaker[AsyncSession]) -> list[DiaryEntry]:
    async with sessionmaker() as session:
        return list(await session.scalars(select(DiaryEntry).order_by(DiaryEntry.id)))


async def test_bot_diary_inline(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.diary.append(analysis())

    await harness.send(ME, "/d проснулся разбитым, ничего не хочется")

    [entry] = await _entries(sessionmaker)
    assert entry.text == "проснулся разбитым, ничего не хочется"
    assert harness.last_text.startswith("📝 Записал в дневник")
    assert "настроение 2/5 · энергия 2/5 · желание 1/5" in harness.last_text
    assert "Что повлияло: плохой сон" in harness.last_text
    # Дневник — не задача: агенту не отправлялось оформление.
    assert [kind for kind, _ in harness.agent.calls] == ["diary"]


async def test_bot_diary_asks_then_saves_voice(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    transcriber = FakeTranscriber("Вечер спокойный, доволен днём")
    harness = BotHarness(sessionmaker, allowed_ids=[ME], transcriber=transcriber)
    harness.agent.diary.append(analysis(mood=4, energy=3, drive=3))

    await harness.send(ME, "/d")
    assert harness.last_text == texts.ASK_DIARY
    await harness.send_voice(ME)

    [entry] = await _entries(sessionmaker)
    assert entry.text == "Вечер спокойный, доволен днём"
    assert "настроение 4/5" in harness.last_text


async def test_bot_diary_cancel_and_agent_down(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await harness.send(ME, "/d")
    await harness.send(ME, "/cancel")
    assert harness.last_text == texts.DIARY_CANCELLED
    assert await _entries(sessionmaker) == []

    harness.agent.diary.append(agent_down())
    await harness.send(ME, "/d устал")
    assert "Агент сейчас недоступен" in harness.last_text
    [entry] = await _entries(sessionmaker)
    assert entry.status == DiaryStatus.FAILED


# Сферы


@pytest.fixture
async def goal_ids(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> dict[str, int]:
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        capital = await goals.create_goal(session, user, "Капитал", "Свобода")
        media = await goals.create_goal(session, user, "Медийка", "Аудитория")
        channel = await goals.create_goal(session, user, "Телеграм канал", None, media)
        await session.commit()
        return {"capital": capital.id, "media": media.id, "channel": channel.id}


def _spheres(entry: DiaryEntry) -> list[tuple[int, int | None, str | None, str | None]]:
    return [(s.goal_id, s.score, s.good, s.bad) for s in entry.spheres]


async def test_entry_is_split_by_spheres(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, goal_ids: dict[str, int]
) -> None:
    agent = FakeAgent()
    result = analysis()
    result.spheres = [
        DiarySphereNote(
            goal_id=goal_ids["capital"], score=2, good=None, bad="Аренда съела подушку"
        ),
        # Направление — это всё равно сфера его цели.
        DiarySphereNote(goal_id=goal_ids["channel"], score=4, good="+40 подписчиков", bad=None),
        DiarySphereNote(goal_id=goal_ids["media"], score=5, good="дубль", bad=None),
        DiarySphereNote(goal_id=9999, score=3, good="чужая цель", bad=None),
    ]
    agent.diary.append(result)
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        outcome = await diary.add_entry(
            session, agent, user, "Деньги тревожат, канал прёт", MORNING
        )

    assert _spheres(outcome.entry) == [
        (goal_ids["capital"], 2, None, "Аренда съела подушку"),
        (goal_ids["media"], 4, "+40 подписчиков", None),
    ]
    context = agent.diary_entries[0]
    assert [g.title for g in context.goals] == ["Капитал", "Медийка"]
    assert context.goals[1].directions[0].title == "Телеграм канал"


async def test_chosen_spheres_are_kept(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, goal_ids: dict[str, int]
) -> None:
    agent = FakeAgent()
    agent.diary.append(analysis())  # агент про сферы ничего не сказал
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        outcome = await diary.add_entry(
            session, agent, user, "Про деньги", MORNING, goal_ids=[goal_ids["capital"]]
        )
        private = await diary.add_entry(
            session, agent, user, "Для себя", MORNING, analyze=False, goal_ids=[goal_ids["channel"]]
        )

    assert agent.diary_entries[0].chosen_goal_ids == (goal_ids["capital"],)
    assert _spheres(outcome.entry) == [(goal_ids["capital"], None, None, None)]
    assert _spheres(private.entry) == [(goal_ids["media"], None, None, None)]


async def test_manual_spheres_survive_reanalysis(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, goal_ids: dict[str, int]
) -> None:
    agent = FakeAgent()
    again = analysis()
    again.spheres = [
        DiarySphereNote(goal_id=goal_ids["capital"], score=1, good=None, bad="всё плохо")
    ]
    agent.diary += [analysis(), again]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        entry = (await diary.add_entry(session, agent, user, "Про канал", MORNING)).entry
        await diary.edit_entry(
            session,
            user,
            entry,
            diary.EntryEdit(spheres=[diary.SphereEdit(goal_ids["media"], 5, "Рост", None)]),
        )
        await diary.reanalyze(session, agent, user, entry)

    assert _spheres(entry) == [(goal_ids["media"], 5, "Рост", None)]


async def test_diary_api_spheres(
    client: httpx.AsyncClient, agent: FakeAgent, goal_ids: dict[str, int]
) -> None:
    about_money = analysis()
    about_money.spheres = [
        DiarySphereNote(goal_id=goal_ids["capital"], score=2, good=None, bad="аренда")
    ]
    agent.diary += [about_money, analysis()]
    money = (await client.post("/api/diary", json={"text": "Деньги"})).json()["entry"]
    other = (
        await client.post("/api/diary", json={"text": "Канал", "goal_ids": [goal_ids["media"]]})
    ).json()["entry"]

    assert money["spheres"] == [
        {"goal_id": goal_ids["capital"], "score": 2, "good": None, "bad": "аренда"}
    ]
    assert other["spheres"][0]["goal_id"] == goal_ids["media"]

    only_money = (await client.get("/api/diary", params={"goal_id": goal_ids["capital"]})).json()
    assert [e["id"] for day in only_money["days"] for e in day["entries"]] == [money["id"]]

    edited = await client.patch(
        f"/api/diary/{money['id']}",
        json={
            "spheres": [
                {"goal_id": goal_ids["capital"], "score": 3, "good": "отложил", "bad": None}
            ]
        },
    )
    assert edited.json()["spheres"] == [
        {"goal_id": goal_ids["capital"], "score": 3, "good": "отложил", "bad": None}
    ]


async def test_bot_diary_shows_spheres(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, goal_ids: dict[str, int]
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    result = analysis()
    result.spheres = [
        DiarySphereNote(goal_id=goal_ids["capital"], score=2, good="отложил 100$", bad="аренда")
    ]
    harness.agent.diary.append(result)

    await harness.send(ME, "/d по деньгам тревожно")

    assert "🎯 <b>Капитал</b> 2/5 — 👍 отложил 100$ · 👎 аренда" in harness.last_text


# XP за записи


async def _xp_events(sessionmaker: async_sessionmaker[AsyncSession]) -> list[tuple[str, int]]:
    async with sessionmaker() as session:
        events = await session.scalars(select(XpEvent).order_by(XpEvent.id))
        return [(event.kind.value, event.amount) for event in events]


async def test_every_entry_earns_xp(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    agent = FakeAgent()
    agent.diary += [analysis(), agent_down()]
    async with sessionmaker() as session:
        user = await _user(session, user_id)
        first = await diary.add_entry(session, agent, user, "Утро", MORNING)
        # Даже если агент недоступен или запись только для себя — факт записи засчитан.
        second = await diary.add_entry(session, agent, user, "День", MORNING)
        third = await diary.add_entry(session, agent, user, "Вечер", MORNING, analyze=False)
        await session.commit()

    assert [first.xp, second.xp, third.xp] == [15, 15, 15]
    assert await _xp_events(sessionmaker) == [("diary", 15)] * 3


async def test_deleted_entry_takes_xp_back(
    client: httpx.AsyncClient, agent: FakeAgent, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    agent.diary.append(analysis())
    created = (await client.post("/api/diary", json={"text": "Проснулся разбитым"})).json()
    assert created["xp"] == 15
    assert (await client.get("/api/summary")).json()["total"]["xp"] == 15

    await client.delete(f"/api/diary/{created['entry']['id']}")

    # Журнал только дописывается: снятие — отдельная запись с минусом.
    assert await _xp_events(sessionmaker) == [("diary", 15), ("diary", -15)]
    assert (await client.get("/api/summary")).json()["total"]["xp"] == 0
    character = (await client.get("/api/character")).json()
    assert character["last_award"]["task_title"] == "Запись удалена"


async def test_bot_diary_shows_xp(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    harness.agent.diary.append(analysis())

    await harness.send(ME, "/d нормально")

    assert harness.last_text.startswith("📝 Записал в дневник · +15 XP")
