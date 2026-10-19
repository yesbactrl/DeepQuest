from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "DeepQuest"


class Settings(BaseSettings):
    """Настройки процесса. Читаются из переменных окружения и файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    # Пустой список включает режим первой настройки: бот отвечает любому
    # пользователю его telegram_id, чтобы его можно было вписать в .env.
    allowed_telegram_ids: Annotated[list[int], NoDecode] = []
    data_dir: Path = DEFAULT_DATA_DIR
    log_level: str = "INFO"

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        if isinstance(value, int):
            return [value]
        return value

    @field_validator("data_dir", mode="after")
    @classmethod
    def _expand_data_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "deepquest.db"
