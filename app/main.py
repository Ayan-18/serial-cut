from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.infrastructure.database import engine, init_db


def create_app() -> FastAPI:
    init_db(engine)
    app = FastAPI(title="SerialCuts", version="0.1.0")
    app.include_router(router)
    static_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()

