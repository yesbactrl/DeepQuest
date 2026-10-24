import tempfile
from collections.abc import AsyncGenerator, AsyncIterator, Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import EditMessageText, GetFile, SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    File,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
    Voice,
)
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from deepquest.agent.base import AgentCallLog, AgentError, AgentResult
from deepquest.agent.schemas import (
    CurrentTask,
    DiaryAnalysis,
    DiaryContext,
    GoalContext,
    PlanResult,
    ReportContext,
    ReviewAnalysis,
    ReviewContext,
    TaskDraft,
    TasksResult,
    ValidationResult,
)
from deepquest.bot.setup import build_dispatcher
from deepquest.db.migrate import upgrade_database
from deepquest.db.session import create_engine, create_sessionmaker
from deepquest.services.proofs import ProofStore

FAKE_FILE_BYTES = b"\x89PNG fake screenshot"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    upgrade_database(path)
    return path


@pytest.fixture
async def engine(db_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(db_path)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


class FakeTelegramSession(BaseSession):
    """Вместо сети записывает запросы бота к Telegram и отвечает правдоподобно."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self._next_message_id = 100
        # id сообщения, которое Telegram присвоил бы каждому SendMessage.
        self.message_ids: dict[int, int] = {}

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, SendMessage):
            self._next_message_id += 1
            self.message_ids[id(method)] = self._next_message_id
            return Message(
                message_id=self._next_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        if isinstance(method, GetFile):
            return File(
                file_id=method.file_id,
                file_unique_id=method.file_id,
                file_path=f"photos/{method.file_id}.jpg",
            )
        return True

    def message_id_of(self, screen: SendMessage | EditMessageText) -> int:
        if isinstance(screen, EditMessageText):
            assert screen.message_id is not None
            return screen.message_id
        return self.message_ids[id(screen)]

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
        # Любой скачанный файл — эти байты: для проверки пруфов-скриншотов этого хватает.
        yield FAKE_FILE_BYTES

    async def close(self) -> None:
        pass


class BotHarness:
    """Диспетчер DeepQuest с фейковым Telegram: шлём апдейты, смотрим ответы."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        allowed_ids: Collection[int],
        agent: FakeAgent | None = None,
        transcriber: FakeTranscriber | None = None,
    ) -> None:
        self.telegram = FakeTelegramSession()
        self.bot = Bot(
            "42:TEST",
            session=self.telegram,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.agent = agent or FakeAgent()
        self.proofs = ProofStore(Path(tempfile.mkdtemp(prefix="deepquest-proofs-")))
        self.dispatcher = build_dispatcher(
            sessionmaker, allowed_ids, self.agent, self.proofs, transcriber
        )
        self._update_id = 0

    def _next_update_id(self) -> int:
        self._update_id += 1
        return self._update_id

    @staticmethod
    def _user(user_id: int) -> TelegramUser:
        return TelegramUser(id=user_id, is_bot=False, first_name="Test")

    async def send(self, user_id: int, text: str) -> None:
        await self._feed_message(user_id, text=text)

    async def send_photo(self, user_id: int, file_id: str, caption: str | None = None) -> None:
        photo = [PhotoSize(file_id=file_id, file_unique_id=file_id, width=1280, height=720)]
        await self._feed_message(user_id, photo=photo, caption=caption)

    async def send_voice(self, user_id: int, file_id: str = "voice-1", seconds: int = 5) -> None:
        voice = Voice(file_id=file_id, file_unique_id=file_id, duration=seconds)
        await self._feed_message(user_id, voice=voice)

    async def _feed_message(self, user_id: int, **content: Any) -> None:
        message = Message(
            message_id=self._update_id + 1000,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=self._user(user_id),
            **content,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._next_update_id(), message=message)
        )

    async def press(self, user_id: int, callback_data: str, message_id: int = 1) -> None:
        question = Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            text="question",
        )
        callback = CallbackQuery(
            id=str(self._update_id),
            from_user=self._user(user_id),
            chat_instance="test",
            data=callback_data,
            message=question,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._next_update_id(), callback_query=callback)
        )

    @property
    def sent(self) -> list[SendMessage]:
        return [r for r in self.telegram.requests if isinstance(r, SendMessage)]

    @property
    def screens(self) -> list[SendMessage | EditMessageText]:
        """Всё, что пользователь видит: новые сообщения и перерисованные."""
        return [r for r in self.telegram.requests if isinstance(r, SendMessage | EditMessageText)]

    @property
    def last_text(self) -> str:
        return self.screens[-1].text

    def find_button(self, label: str, on: str | None = None) -> tuple[str, int]:
        """callback_data и id сообщения кнопки с этим текстом.

        Ищет на последнем экране с клавиатурой, а с `on` — на последнем экране,
        в тексте которого есть `on`.
        """
        for screen in reversed(self.screens):
            if not isinstance(screen.reply_markup, InlineKeyboardMarkup):
                continue
            if on is not None and on not in screen.text:
                continue
            for row in screen.reply_markup.inline_keyboard:
                for button in row:
                    if label in button.text and button.callback_data:
                        return button.callback_data, self.telegram.message_id_of(screen)
            raise AssertionError(f"No button {label!r} on the keyboard")
        raise AssertionError("No keyboard was shown")

    def button(self, label: str, on: str | None = None) -> str:
        return self.find_button(label, on)[0]

    async def tap(self, user_id: int, label: str, on: str | None = None) -> None:
        callback_data, message_id = self.find_button(label, on)
        await self.press(user_id, callback_data, message_id)


def draft(
    title: str,
    goal_id: int | None = None,
    minutes: int = 60,
    mult: float = 1.0,
    reason: str = "обычная работа",
) -> TaskDraft:
    return TaskDraft(
        title=title,
        expected_result=f"Сделано: {title}",
        goal_id=goal_id,
        estimate_min=minutes,
        value_mult=mult,  # type: ignore[arg-type]
        mult_reason=reason,
    )


def agent_down() -> AgentError:
    log = AgentCallLog(
        kind="test", prompt_version="test", model="fake", request={}, error="API down"
    )
    return AgentError("API down", [log])


class FakeAgent:
    """Агент по сценарию: каждый вызов берёт следующий ответ из очереди (или бросает ошибку)."""

    def __init__(self) -> None:
        self.plans: list[PlanResult | AgentError] = []
        self.answers: list[TasksResult | AgentError] = []
        self.revisions: list[TaskDraft | AgentError] = []
        self.validations: list[ValidationResult | AgentError] = []
        self.diary: list[DiaryAnalysis | AgentError] = []
        self.diary_entries: list[DiaryContext] = []
        self.reviews: list[ReviewAnalysis | AgentError] = []
        self.review_contexts: list[ReviewContext] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reports: list[ReportContext] = []

    @staticmethod
    def _next[T](queue: list[T | AgentError], kind: str) -> AgentResult[T]:
        assert queue, f"FakeAgent: no scripted response for {kind}"
        item = queue.pop(0)
        if isinstance(item, AgentError):
            raise item
        log = AgentCallLog(kind=kind, prompt_version="test", model="fake", request={})
        return AgentResult(item, [log])

    async def plan_task(self, text: str, goals: Sequence[GoalContext]) -> AgentResult[PlanResult]:
        self.calls.append(("plan_task", {"text": text, "goals": goals}))
        return self._next(self.plans, "plan_task")

    async def answer_clarification(
        self, text: str, question: str, answer: str, goals: Sequence[GoalContext]
    ) -> AgentResult[TasksResult]:
        self.calls.append(("answer", {"text": text, "question": question, "answer": answer}))
        return self._next(self.answers, "plan_task_answer")

    async def revise_task(
        self,
        text: str,
        current: CurrentTask,
        correction: str | None,
        goals: Sequence[GoalContext],
    ) -> AgentResult[TaskDraft]:
        self.calls.append(("revise", {"text": text, "current": current, "correction": correction}))
        return self._next(self.revisions, "plan_task_revise")

    async def analyze_diary(self, entry: DiaryContext) -> AgentResult[DiaryAnalysis]:
        self.diary_entries.append(entry)
        self.calls.append(("diary", {"entry": entry}))
        return self._next(self.diary, "analyze_diary")

    async def review_period(self, review: ReviewContext) -> AgentResult[ReviewAnalysis]:
        self.review_contexts.append(review)
        self.calls.append(("review", {"review": review}))
        return self._next(self.reviews, "review_period")

    async def validate_report(self, report: ReportContext) -> AgentResult[ValidationResult]:
        self.reports.append(report)
        self.calls.append(("validate", {"report": report}))
        return self._next(self.validations, "validate_report")


def verdict(kind: str = "accepted", comment: str = "Реальный шаг.") -> ValidationResult:
    return ValidationResult(verdict=kind, reason=f"Причина: {kind}", comment=comment)  # type: ignore[arg-type]


class FakeTranscriber:
    """Распознавание по сценарию: каждый вызов берёт следующий текст (или бросает ошибку)."""

    def __init__(self, *results: str | Exception) -> None:
        self.results = list(results)
        self.received: list[bytes] = []

    async def transcribe(self, audio: bytes) -> str:
        self.received.append(audio)
        assert self.results, "FakeTranscriber: no scripted transcript"
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result
