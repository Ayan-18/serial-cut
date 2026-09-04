"""Fail if the SQLAlchemy models have drifted from the Alembic migrations.

Runs the same comparison Alembic's autogenerate uses. CI calls this right after
`alembic upgrade head` so a forgotten migration is caught before merge.

    .\\.venv\\Scripts\\python.exe scripts\\check_migrations.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.infrastructure.config import get_settings  # noqa: E402
from app.models import entities  # noqa: E402,F401  (registers every table)
from app.models.base import Base  # noqa: E402

# Types Alembic cannot round-trip on SQLite (length/variant only) — ignore those.
_IGNORED_OPS = {"modify_type", "modify_default", "modify_nullable"}


def _include_name(name, type_, parent_names) -> bool:
    # FTS5 search tables (and their shadow tables) are created at runtime by
    # global_search._ensure_search_indexes, not by Alembic.
    if type_ == "table" and name and "_search" in name:
        return False
    return True


def main() -> int:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": False,
                "compare_server_default": False,
                "include_name": _include_name,
            },
        )
        diff = [op for op in compare_metadata(context, Base.metadata) if _kind(op) not in _IGNORED_OPS]

    if not diff:
        print("Schema matches models — no missing migration.")
        return 0

    print("Models have drifted from the migrations. Generate one:\n")
    print("  .\\.venv\\Scripts\\python.exe -m alembic revision --autogenerate -m \"<desc>\"\n")
    for op in diff:
        print(f"  - {op}")
    return 1


def _kind(op: object) -> str:
    if isinstance(op, tuple) and op:
        return str(op[0])
    return getattr(op, "__visit_name__", type(op).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
