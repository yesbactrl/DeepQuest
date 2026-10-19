"""Отчёт из сообщения Telegram: текст, ссылки, скриншоты и файлы-пруфы."""

import logging
import re
from typing import Any

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from deepquest.agent.schemas import ProofImage
from deepquest.services.validation import ReportInput

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")
# Форматы картинок, которые понимает Claude.
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def extract_report(message: Message) -> ReportInput:
    text = (message.text or message.caption or "").strip()
    entities = message.entities or message.caption_entities or []
    links = URL_RE.findall(text)
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
            }
        )
    return ReportInput(text=text, links=list(dict.fromkeys(links)), files=files)


async def download_images(bot: Bot, proofs: list[dict[str, Any]]) -> list[ProofImage]:
    """Скачивает картинки-пруфы для агента. Что не скачалось, агент просто не увидит."""
    images: list[ProofImage] = []
    for proof in proofs:
        if len(images) >= MAX_IMAGES:
            break
        if proof.get("mime_type") not in IMAGE_TYPES or not proof.get("file_id"):
            continue
        try:
            buffer = await bot.download(proof["file_id"])
        except (TelegramAPIError, aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("Cannot download proof %s: %s", proof["file_id"], exc)
            continue
        data = buffer.read() if buffer is not None else b""
        if data and len(data) <= MAX_IMAGE_BYTES:
            images.append(ProofImage(media_type=proof["mime_type"], data=data))
    return images
