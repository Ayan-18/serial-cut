from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.infrastructure.config import get_settings
from app.models.base import Base
from app.models import entities  # noqa: F401

config = context.config
database_url = get_settings().database_url
if database_url.startswith("sqlite:///"):
    database_path = database_url.removeprefix("sqlite:///")
    if database_path and database_path != ":memory:":
        Path(database_path).expanduser().resolve(strict=False).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

