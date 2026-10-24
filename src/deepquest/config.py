from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "DeepQuest"
DEFAULT_CACHE_DIR = Path.home() / "Library" / "Caches" / "DeepQuest"
# Корень репозитория: src/deepquest/config.py → три уровня вверх.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AgentSettings(BaseSettings):
    """Настройки агента. Отдельно от бота, чтобы проверять промпты без токена Telegram."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # subscription — через Claude Code по твоей подписке Pro/Max (только для личного бота);
    # api — платные запросы по ключу ANTHROPIC_API_KEY.
    agent_backend: Literal["subscription", "api"] = "subscription"
    # При сбое подписки (например, кончились лимиты) повторить запрос через API. Платно.
    agent_api_fallback: bool = False
    # Под launchd PATH короче, чем в терминале: там лучше указать полный путь.
    claude_code_path: str = "claude"
    claude_code_timeout_s: float = 120.0
    agent_workdir: Path = DEFAULT_CACHE_DIR / "agent"

    # Без ключа SDK ищет ANTHROPIC_API_KEY в окружении и профиль `ant auth login`.
    anthropic_api_key: SecretStr | None = None
    agent_plan_model: str = "claude-haiku-5-5"
    agent_fallback_model: str = "claude-opus-5-5"
    agent_plan_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_validate_model: str = "claude-opus-5-5"
    agent_validate_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    agent_timeout_s: float = 60.0


class Settings(AgentSettings):
    """Настройки процесса. Читаются из переменных окружения и файла .env."""

    # Бот в Telegram можно выключить: тогда процесс поднимает только веб, а токен не нужен.
    bot_enabled: bool = True
    bot_token: SecretStr | None = None
    # Пустой список включает режим первой настройки: бот отвечает любому
    # пользователю его telegram_id, чтобы его можно было вписать в .env.
    allowed_telegram_ids: Annotated[list[int], NoDecode] = []
    data_dir: Path = DEFAULT_DATA_DIR
    log_level: str = "INFO"

    # Веб открывается только с этого Mac: входа нет, поэтому наружу его не выставляем.
    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8484
    web_dist_dir: Path = PROJECT_ROOT / "web" / "dist"
    # Журнал каждого запроса к вебу. В службе (launchd) выключен: фронтенд опрашивает таймер
    # каждые несколько секунд, и лог за день разрастался бы на мегабайты.
    access_log: bool = True

    # Голосовой ввод: локальный Whisper. Модель (~1,5 ГБ) скачается при первом запуске.
    voice_enabled: bool = True
    voice_model: str = "large-v3-turbo"
    # Пусто — язык определяется сам; с явным «ru» короткие фразы распознаются надёжнее.
    voice_language: str = "ru"

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.replace(" ", "").split(",") if part]
        if isinstance(value, int):
            return [value]
        return value

    @model_validator(mode="after")
    def _token_if_bot(self) -> Settings:
        if self.bot_enabled and self.bot_token is None:
            raise ValueError("BOT_TOKEN не задан: впиши его или выключи бота (BOT_ENABLED=false)")
        return self

    @field_validator("data_dir", mode="after")
    @classmethod
    def _expand_data_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "deepquest.db"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"
