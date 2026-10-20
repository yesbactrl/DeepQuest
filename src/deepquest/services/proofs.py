"""Пруфы отчётов: скриншоты из Telegram (по file_id) и файлы, загруженные через веб.

Отчёт может прийти из бота, а перепроверяться из веба, и наоборот, поэтому читает пруфы
одно место. Telegram-файлы скачивает переданная функция: у сервиса нет своего бота.
"""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from deepquest.agent.schemas import ProofImage

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")
# Форматы картинок, которые понимает Claude.
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}

TelegramDownload = Callable[[str], Awaitable[bytes]]


def extract_links(text: str) -> list[str]:
    return list(dict.fromkeys(URL_RE.findall(text)))


def is_image(proof: dict[str, Any]) -> bool:
    return proof.get("mime_type") in IMAGE_TYPES


class ProofStore:
    def __init__(self, files_dir: Path) -> None:
        self._dir = files_dir

    def save_upload(
        self, task_id: int, filename: str, mime_type: str, data: bytes
    ) -> dict[str, Any]:
        """Сохраняет файл из веба и возвращает запись для `reports.proofs`."""
        folder = self._dir / str(task_id)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{EXTENSIONS.get(mime_type, '')}"
        (folder / name).write_bytes(data)
        return {
            "kind": "upload",
            "path": f"{task_id}/{name}",
            "mime_type": mime_type,
            "name": filename,
        }

    def upload_path(self, proof: dict[str, Any]) -> Path | None:
        """Путь к загруженному файлу; None, если запись не про файл или путь ведёт наружу."""
        if proof.get("kind") != "upload" or not proof.get("path"):
            return None
        root = self._dir.resolve()
        path = (root / proof["path"]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None

    async def read(self, proof: dict[str, Any], telegram: TelegramDownload | None) -> bytes | None:
        if (path := self.upload_path(proof)) is not None:
            return path.read_bytes()
        if proof.get("kind") in {"photo", "document"} and proof.get("file_id") and telegram:
            try:
                return await telegram(proof["file_id"])
            except Exception as exc:  # сеть, Telegram, что угодно — агент обойдётся без картинки
                logger.warning("Cannot download Telegram proof %s: %s", proof["file_id"], exc)
        return None

    async def images(
        self, proofs: list[dict[str, Any]], telegram: TelegramDownload | None = None
    ) -> list[ProofImage]:
        """Картинки-пруфы для агента. Что не прочиталось, агент просто не увидит."""
        result: list[ProofImage] = []
        for proof in proofs:
            if len(result) >= MAX_IMAGES:
                break
            if not is_image(proof):
                continue
            data = await self.read(proof, telegram)
            if data and len(data) <= MAX_IMAGE_BYTES:
                result.append(ProofImage(media_type=proof["mime_type"], data=data))
        return result


def sniff_image_type(data: bytes) -> str | None:
    """Тип картинки по первым байтам: браузеру на слово не верим, агенту нужен точный тип."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
