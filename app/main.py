from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers.courses import router as courses_router
from app.routers.dashboard import router as dashboard_router
from app.routers.resources import router as resources_router
from app.routers.sessions import router as sessions_router


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_storage()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")
    app.include_router(dashboard_router)
    app.include_router(courses_router)
    app.include_router(resources_router)
    app.include_router(sessions_router)
    app.state.settings = settings

    return app


app = create_app()
