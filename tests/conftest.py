from __future__ import annotations

import pytest

from app.infrastructure.database import init_db, make_session_factory
from app.models.base import Base
from sqlalchemy import create_engine


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        yield db
    Base.metadata.drop_all(engine)

