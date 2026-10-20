"""Отчёт из сообщения Telegram: текст, ссылки, скриншоты и файлы-пруфы."""

from typing import Any

from aiogram import Bot
from aiogram.types import Message

from deepquest.services.proofs import TelegramDownload, extract_links
from deepquest.services.validation import ReportInput


def extract_report(message: Message) -> ReportInput:
    text = (message.text or message.caption or "").strip()
    entities = message.entities or message.caption_entities or []
    links = extract_links(text)
    links += [e.url for e in entities if e.type == "text_link" and e.url and e.url not in links]

    files: list[dict[str, Any]] = []
    if message.photo:
        # Telegram присылает несколько размеров: последний — самый большой.
        files.append(
            {"kind": "photo", "file_id": message.photo[-1].file_id, "mime_type": "image/jpeg"}
        )
    if message.document:
        files.append(
            {
                "kind": "document",
                "file_id": message.document.file_id,
                "mime_type": message.document.mime_type or "application/octet-stream",
                "name": message.document.file_name,
            }
        )
    return ReportInput(text=text, links=links, files=files)


def telegram_download(bot: Bot) -> TelegramDownload:
    """Функция скачивания файла Telegram для ProofStore."""

    async def download(file_id: str) -> bytes:
        buffer = await bot.download(file_id)
        return buffer.read() if buffer is not None else b""

    return download
