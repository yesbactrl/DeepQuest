# DeepQuest

Telegram-бот для личной прокачки: цели, задачи, таймер, отчёты, которые проверяет Claude, и XP за реальные шаги.

- Что строим: [docs/product-spec.md](docs/product-spec.md)
- Как устроено: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Запуск

Нужен [uv](https://docs.astral.sh/uv/).

1. Создай бота в [@BotFather](https://t.me/BotFather) и получи токен.
2. Скопируй настройки и впиши токен в `BOT_TOKEN`:

   ```bash
   cp .env.example .env
   ```

3. Запусти бота:

   ```bash
   uv run deepquest
   ```

4. Напиши боту что угодно. Пока `ALLOWED_TELEGRAM_IDS` пуст, он ответит твоим telegram_id. Впиши id в `.env`, перезапусти бота и отправь `/start`.

База лежит в `~/Library/Application Support/DeepQuest/deepquest.db`, миграции применяются сами при старте.

## Разработка

```bash
uv run pytest
```

```bash
uv run ruff check . && uv run ruff format --check .
```

Новая миграция после изменения `db/models.py` (CLI работает с черновой базой в `./data`):

```bash
uv run alembic upgrade head && uv run alembic revision --autogenerate -m "что изменилось"
```
