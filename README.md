# DeepQuest

Telegram-бот для личной прокачки: цели, задачи, таймер, отчёты, которые проверяет Claude, и XP за реальные шаги.

- Что строим: [docs/product-spec.md](docs/product-spec.md)
- Как устроено: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Запуск

Нужен [uv](https://docs.astral.sh/uv/).

1. Создай бота в [@BotFather](https://t.me/BotFather) и получи токен.
2. Скопируй настройки и впиши токен в `BOT_TOKEN`, а ключ Claude API — в `ANTHROPIC_API_KEY` (без ключа задачи сохраняются без оценки):

   ```bash
   cp .env.example .env
   ```

3. Запусти бота:

   ```bash
   uv run deepquest
   ```

4. Напиши боту что угодно. Пока `ALLOWED_TELEGRAM_IDS` пуст, он ответит твоим telegram_id. Впиши id в `.env`, перезапусти бота и отправь `/start`.

База лежит в `~/Library/Application Support/DeepQuest/deepquest.db`, миграции применяются сами при старте.

После онбординга любое сообщение боту — это новая задача: агент оформит карточку, а ты сохранишь её в бэклог (`/backlog`), поправишь или отменишь. Цели — `/goals`.

## Разработка

```bash
uv run pytest
```

```bash
uv run ruff check . && uv run ruff format --check .
```

Проверить промпт оформления задач на настоящем API, без Telegram (нужен `ANTHROPIC_API_KEY`; цели демонстрационные):

```bash
uv run python -m deepquest.agent "надо бы глянуть, как люди льют на тиктоке, и запустить кампанию баксов на двадцать"
```

Новая миграция после изменения `db/models.py` (CLI работает с черновой базой в `./data`):

```bash
uv run alembic upgrade head && uv run alembic revision --autogenerate -m "что изменилось"
```
