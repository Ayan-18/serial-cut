from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.config import Settings, get_settings
from app.models.base import Base


def _ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path and raw_path != ":memory:":
        Path(raw_path).expanduser().resolve(strict=False).parent.mkdir(parents=True, exist_ok=True)


def make_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    _ensure_sqlite_parent(settings.database_url)
    is_sqlite = settings.database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
    engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    if is_sqlite:
        event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # Another already-running process can temporarily prevent switching
            # the journal mode. The connection remains usable and retries writes
            # through busy_timeout; the next idle connection enables WAL.
            pass
    finally:
        cursor.close()


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def require_migrated_database(engine: Engine) -> None:
    """Refuse startup when Alembic was skipped instead of creating an unversioned schema."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    if not inspect(engine).has_table("alembic_version"):
        raise RuntimeError(
            "База SerialCuts не мигрирована. Выполните: .\\.venv\\Scripts\\python.exe -m alembic upgrade head"
        )
    config_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    expected_heads = set(ScriptDirectory.from_config(Config(str(config_path))).get_heads())
    with engine.connect() as connection:
        current_heads = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if current_heads != expected_heads:
        current = ", ".join(sorted(current_heads)) or "нет версии"
        expected = ", ".join(sorted(expected_heads))
        raise RuntimeError(
            f"Версия базы устарела ({current}; нужна {expected}). "
            "Выполните: .\\.venv\\Scripts\\python.exe -m alembic upgrade head"
        )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


engine = make_engine()
SessionLocal = make_session_factory(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session] = SessionLocal) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

