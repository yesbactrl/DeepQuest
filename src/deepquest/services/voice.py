"""Голос → текст. Распознаёт локальный Whisper (faster-whisper) прямо на Маке: бесплатно,
без облака, запись никуда не уходит. Модель (~1,5 ГБ) скачивается один раз в data_dir/models.
"""

import asyncio
import contextlib
import io
import logging
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Дольше — это уже не «надиктовать задачу», а распознавание на минуты.
MAX_VOICE_SECONDS = 5 * 60
MAX_AUDIO_BYTES = 25 * 1024 * 1024

# Whisper учился на субтитрах и на тишине в конце иногда «дописывает» их титры.
_PHANTOM_TAIL = re.compile(
    r"(?:^|(?<=[\s.,!?…]))\s*(?:продолжение следует|спасибо за просмотр"
    r"|субтитры (?:сделал|создавал)[^.!?…]*|редактор субтитров[^.!?…]*)[\s.!…]*$",
    re.IGNORECASE,
)


class VoiceError(Exception):
    """Запись не распознать. Текст ошибки показывается пользователю."""


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes) -> str:
        """Текст записи (ogg из Telegram, webm или mp4 из браузера); пустой — если речи нет."""
        ...


def clean_transcript(segments: list[str]) -> str:
    text = " ".join(segment.strip() for segment in segments).strip()
    while (cleaned := _PHANTOM_TAIL.sub("", text).rstrip(" ,")) != text:
        text = cleaned
    return text


async def _in_daemon_thread[T](fn: Callable[[], T]) -> T:
    """Как asyncio.to_thread, но поток-демон: Ctrl+C не ждёт, пока докачается модель."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def deliver(result: T | None, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)  # type: ignore[arg-type]

    def run() -> None:
        result: T | None = None
        error: BaseException | None = None
        try:
            result = fn()
        except BaseException as exc:
            error = exc
        with contextlib.suppress(RuntimeError):  # цикл уже закрыт: процесс выходит
            loop.call_soon_threadsafe(deliver, result, error)

    threading.Thread(target=run, name="whisper", daemon=True).start()
    return await future


class WhisperTranscriber:
    def __init__(self, model: str, language: str | None, models_dir: Path) -> None:
        self._model_name = model
        self._language = language
        self._models_dir = models_dir
        self._model: WhisperModel | None = None
        # Распознаём по одной записи: модель и так занимает все ядра.
        self._lock = asyncio.Lock()

    @property
    def description(self) -> str:
        return f"Whisper {self._model_name}, локально"

    async def warm_up(self) -> None:
        """Загружает модель заранее (в первый раз — скачивает), чтобы первое голосовое не ждало."""
        try:
            async with self._lock:
                await _in_daemon_thread(self._load)
        except Exception:
            logger.exception("Модель распознавания речи не загрузилась")
        else:
            logger.info("Распознавание речи готово")

    async def transcribe(self, audio: bytes) -> str:
        async with self._lock:
            return await _in_daemon_thread(lambda: self._transcribe(audio))

    def _load(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type="int8",
                # По умолчанию 4 потока; на 8 вдвое быстрее, дальше прирост мал.
                cpu_threads=min(8, os.cpu_count() or 4),
                download_root=str(self._models_dir),
            )
        return self._model

    def _transcribe(self, audio: bytes) -> str:
        import av

        model = self._load()
        try:
            segments, info = model.transcribe(
                io.BytesIO(audio),
                language=self._language,
                vad_filter=True,
                beam_size=5,
                # Без опоры на предыдущий текст и без таймкодов Whisper быстрее и меньше выдумывает.
                condition_on_previous_text=False,
                without_timestamps=True,
            )
        except av.error.FFmpegError as exc:
            raise VoiceError("Не получилось прочитать запись.") from exc
        if info.duration > MAX_VOICE_SECONDS:
            raise VoiceError(f"Запись длиннее {MAX_VOICE_SECONDS // 60} минут.")
        return clean_transcript([segment.text for segment in segments])
