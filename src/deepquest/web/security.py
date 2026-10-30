"""Защита веба, который слушает только этот Mac и работает без входа.

С телефона веб открывается через Tailscale (`tailscale serve`): попасть туда могут только
устройства из твоей сети Tailscale, а до DeepQuest запрос доходит с localhost. Пароль
поэтому не нужен.

Слушать 127.0.0.1 мало: страница любого сайта в том же браузере может слать запросы
на localhost. Поэтому:
- принимаем только Host `localhost` / `127.0.0.1` / `[::1]` и явно названные в настройке
  `WEB_HOSTS` (имя Mac в Tailscale) — против DNS rebinding, когда чужой домен начинает
  указывать на 127.0.0.1;
- запросы, которые меняют данные, требуют заголовок `X-DeepQuest`. Простая форма
  или fetch с чужого сайта его не пришлёт: нестандартный заголовок требует CORS-preflight,
  а CORS мы не разрешаем никому — значит, и CSRF не пройдёт.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "::1"]
CSRF_HEADER = "X-DeepQuest"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.url.path.startswith("/api/")
            and request.method not in SAFE_METHODS
            and request.headers.get(CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": f"Нужен заголовок {CSRF_HEADER}: 1"}, status_code=403)
        return await call_next(request)
