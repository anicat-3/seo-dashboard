"""Точка входа веб-приложения FastAPI.

Запуск для разработки::

    uvicorn app.main:app --reload

API доступно по ``/api``, собранный фронтенд (``frontend/dist``) раздаётся с корня.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api.routes import (
    admin,
    auth,
    credentials,
    dashboard,
    feedback,
    oauth,
    projects,
    signals,
    team,
)
from app.config import get_settings
from app.db import get_engine
from app.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)

#: Методы, изменяющие состояние; для них требуется заголовок против CSRF.
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Запустить планировщик при старте и остановить при завершении."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    start_scheduler()
    yield
    shutdown_scheduler()


def create_app() -> FastAPI:
    """Создать и настроить приложение."""
    settings = get_settings()
    app = FastAPI(title="SEO-дашборд", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        """Требовать ``X-Requested-With`` для изменяющих запросов к API.

        Браузер не может отправить такой заголовок с чужого сайта без CORS-разрешения,
        а CORS в приложении не включён.
        """
        if (request.url.path.startswith("/api/") and request.method in UNSAFE_METHODS
                and CSRF_HEADER not in request.headers):
            return JSONResponse({"detail": "Отсутствует заголовок X-Requested-With"},
                                status_code=403)
        return await call_next(request)

    app.add_middleware(
        SessionMiddleware, secret_key=settings.secret_key, session_cookie="seo_session",
        max_age=settings.session_max_age_days * 24 * 3600, same_site="lax",
        https_only=settings.session_cookie_secure,
    )

    for module in (auth, credentials, projects, dashboard, signals, admin, team, oauth,
                   feedback):
        app.include_router(module.router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        """Проверка работоспособности приложения и БД."""
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist) -> None:
    """Раздавать собранный SPA; все неизвестные пути отдают ``index.html``."""
    index = dist / "index.html"
    if not index.exists():
        logger.warning("Фронтенд не собран (%s не найден): доступно только API", index)
        return
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
