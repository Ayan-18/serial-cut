from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.queue_routes import router as queue_router
from app.api.search_routes import router as search_router
from app.infrastructure.database import engine, init_db
from app.workers.background import background_queue


@asynccontextmanager
async def lifespan(_: FastAPI):
    background_queue.start()
    try:
        yield
    finally:
        background_queue.stop()


def create_app() -> FastAPI:
    init_db(engine)
    app = FastAPI(title="SerialCuts", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(queue_router)
    app.include_router(search_router)
    static_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()

