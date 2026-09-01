from __future__ import annotations

import pytest

from app.infrastructure.database import init_db, make_session_factory
from app.models.base import Base
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        yield db
    Base.metadata.drop_all(engine)


@pytest.fixture()
def api_client():
    """FastAPI TestClient on an isolated in-memory schema (no real DB, no lifespan).

    Uses ``StaticPool`` so the single connection is shared with the anyio worker
    thread FastAPI runs sync endpoints on.
    """
    from fastapi.testclient import TestClient

    from app.api.dependencies import get_session
    from app.main import app

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    factory = make_session_factory(engine)

    def override_get_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        client.db = factory  # type: ignore[attr-defined]
        yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()

