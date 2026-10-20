"""Веб-приложение: JSON-API под /api и собранный React-фронтенд."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from deepquest.agent.base import TaskAgent
from deepquest.services.proofs import ProofStore, TelegramDownload
from deepquest.web.deps import WebContext
from deepquest.web.routes import dashboard, goals, me, tasks
from deepquest.web.security import ALLOWED_HOSTS, CsrfHeaderMiddleware

NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>DeepQuest</title>
<body style="font-family: system-ui; padding: 2rem">
<h1>Фронтенд ещё не собран</h1>
<p>Выполни в папке <code>web</code>: <code>npm install</code> и <code>npm run build</code>,
а для разработки — <code>npm run dev</code>.</p>
</body>"""


def create_app(
    sessionmaker: async_sessionmaker[AsyncSession],
    owner_telegram_id: int | None,
    dist_dir: Path,
    agent: TaskAgent,
    proofs: ProofStore,
    telegram_download: TelegramDownload | None = None,
) -> FastAPI:
    app = FastAPI(
        title="DeepQuest",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.context = WebContext(
        sessionmaker, owner_telegram_id, agent, proofs, telegram_download
    )
    app.add_middleware(CsrfHeaderMiddleware)
    # Последним добавленный middleware срабатывает первым: Host проверяем раньше всего.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    app.include_router(me.router)
    app.include_router(goals.router)
    app.include_router(tasks.router)
    app.include_router(dashboard.router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
    async def unknown_api(path: str) -> None:
        # Иначе неизвестный адрес API ушёл бы в index.html фронтенда.
        raise HTTPException(404, "Нет такого адреса API")

    _mount_frontend(app, dist_dir)
    return app


def _mount_frontend(app: FastAPI, dist_dir: Path) -> None:
    index = dist_dir / "index.html"
    if not index.is_file():

        @app.get("/{path:path}", include_in_schema=False)
        async def not_built(path: str) -> HTMLResponse:
            return HTMLResponse(NOT_BUILT, status_code=503)

        return

    root = dist_dir.resolve()
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        # Файлы из сборки (favicon и т.п.) отдаём как есть, остальное — index.html:
        # маршрутизацию по страницам делает React.
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
