from __future__ import annotations

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import domain_routers
from app.api.errors import register_exception_handlers
from app.api.loopback import LoopbackOnlyMiddleware
from app.api.events_routes import router as events_router
from app.api.queue_routes import router as queue_router
from app.api.search_routes import router as search_router
from app.infrastructure.config import get_settings
from app.infrastructure.database import engine, require_migrated_database
from app.infrastructure.logging_config import configure_logging
from app.workers.background import background_queue


@asynccontextmanager
async def lifespan(_: FastAPI):
    background_queue.start()
    try:
        yield
    finally:
        background_queue.stop()


def create_app() -> FastAPI:
    configure_logging(get_settings())
    require_migrated_database(engine)
    app = FastAPI(title="SerialCuts", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(LoopbackOnlyMiddleware)
    for domain_router in domain_routers:
        app.include_router(domain_router)
    app.include_router(queue_router)
    app.include_router(search_router)
    app.include_router(events_router)
    static_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()

