from datetime import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepquest.bot import texts
from deepquest.bot.keyboards import ClockCb, NormCb, SettingsCb, TimezoneCb
from deepquest.db.models import User
from tests.conftest import BotHarness

ME = 111
STRANGER = 222


async def _load_user(sessionmaker: async_sessionmaker[AsyncSession]) -> User:
    async with sessionmaker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == ME))
        assert user is not None
        return user


async def test_strangers_are_ignored(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(STRANGER, "/start")

    assert harness.telegram.requests == []
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_setup_mode_tells_telegram_id(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[])

    await harness.send(STRANGER, "/start")

    assert len(harness.sent) == 1
    assert f"ALLOWED_TELEGRAM_IDS={STRANGER}" in harness.last_text


async def test_onboarding_with_buttons_and_text(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.send(ME, "/start")
    assert harness.sent[0].text == texts.WELCOME
    assert harness.last_text == texts.ASK_TIMEZONE

    await harness.press(ME, TimezoneCb(name="Europe/Moscow").pack())
    assert texts.ASK_DAILY_NORM in harness.last_text

    await harness.send(ME, "1.5 ч")
    assert texts.ASK_MORNING in harness.last_text

    await harness.press(ME, ClockCb.of(time(8)).pack())
    assert texts.ASK_EVENING in harness.last_text

    await harness.send(ME, "21:30")
    assert "Готово" in harness.sent[-2].text
    assert texts.GOALS_AFTER_ONBOARDING in harness.sent[-2].text
    assert harness.last_text == texts.ASK_GOAL_TITLE

    user = await _load_user(sessionmaker)
    assert user.tz == "Europe/Moscow"
    assert user.daily_norm_min == 90
    assert user.morning_at == time(8)
    assert user.evening_at == time(21, 30)
    assert user.onboarded_at is not None


async def test_onboarding_survives_restart(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    await BotHarness(sessionmaker, allowed_ids=[ME]).send(ME, "/start")

    # Новый диспетчер — как после перезапуска процесса. Состояние должно прийти из базы.
    restarted = BotHarness(sessionmaker, allowed_ids=[ME])
    await restarted.send(ME, "Бангкок")

    assert texts.ASK_DAILY_NORM in restarted.last_text
    assert (await _load_user(sessionmaker)).tz == "Asia/Bangkok"


async def test_wrong_answers_keep_the_step(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await harness.send(ME, "/start")

    await harness.send(ME, "Нарния")
    assert harness.last_text == texts.TIMEZONE_NOT_UNDERSTOOD

    await harness.send(ME, "+7")
    await harness.send(ME, "5 мин")
    assert harness.last_text == texts.DAILY_NORM_NOT_UNDERSTOOD

    await harness.press(ME, NormCb(minutes=60).pack())
    await harness.send(ME, "10:00")
    await harness.send(ME, "9")
    assert harness.last_text == texts.evening_before_morning(time(10))

    await harness.send(ME, "22")
    user = await _load_user(sessionmaker)
    assert (user.tz, user.daily_norm_min, user.evening_at) == ("Etc/GMT-7", 60, time(22))


async def test_cancel_during_onboarding(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    await harness.send(ME, "/start")

    await harness.send(ME, "/cancel")
    assert harness.last_text == texts.CANCELLED

    await harness.send(ME, "привет")
    assert harness.last_text == texts.NEED_ONBOARDING


async def test_settings_redo_keeps_first_onboarding_date(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])
    for step in ("/start", "+3", "60", "9", "21"):
        await harness.send(ME, step)
    first_onboarded_at = (await _load_user(sessionmaker)).onboarded_at

    await harness.send(ME, "/start")
    assert "С возвращением" in harness.last_text

    await harness.press(ME, SettingsCb(action="redo").pack())
    for step in ("+7", "120", "8", "22"):
        await harness.send(ME, step)

    user = await _load_user(sessionmaker)
    assert (user.tz, user.daily_norm_min) == ("Etc/GMT-7", 120)
    assert user.onboarded_at == first_onboarded_at


async def test_stale_button_is_answered(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    harness = BotHarness(sessionmaker, allowed_ids=[ME])

    await harness.press(ME, TimezoneCb(name="Europe/Moscow").pack())

    answer = harness.telegram.requests[-1]
    assert getattr(answer, "text", None) == texts.STALE_BUTTON
    assert harness.sent == []
