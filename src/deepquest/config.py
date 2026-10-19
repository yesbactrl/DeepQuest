from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "DeepQuest"


class AgentSettings(BaseSettings):
    """Настройки агента. Отдельно от бота, чтобы проверять промпты без токена Telegram."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Без ключа SDK ищет ANTHROPIC_API_KEY в окружении и профиль `ant auth login`.
    anthropic_api_key: SecretStr | None = None
    agent_plan_model: str = "claude-haiku-5-5"
    agent_fallback_model: str = "claude-opus-5-5"
    agent_plan_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_timeout_s: float = 60.0


class Settings(AgentSettings):
    """Настройки процесса. Читаются из переменных окружения и файла .env."""

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
