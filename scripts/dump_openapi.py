"""Regenerate docs/openapi.json and docs/API.md from the live FastAPI app.

Run after adding or changing an endpoint:

    .\\.venv\\Scripts\\python.exe scripts\\dump_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app  # noqa: E402

DOCS_DIR = PROJECT_ROOT / "docs"
OPENAPI_PATH = DOCS_DIR / "openapi.json"
MARKDOWN_PATH = DOCS_DIR / "API.md"

_METHOD_ORDER = ["get", "post", "put", "patch", "delete"]


def build_openapi() -> dict:
    schema = app.openapi()
    # Drop the ever-changing FastAPI version string so the file only churns on
    # real API changes.
    schema.get("info", {}).pop("version", None)
    return schema


def _group(path: str) -> str:
    parts = [part for part in path.split("/") if part and not part.startswith("{")]
    return parts[1] if len(parts) > 1 else "root"


def build_markdown(schema: dict) -> str:
    rows: dict[str, list[str]] = {}
    for path, methods in sorted(schema.get("paths", {}).items()):
        for method in _METHOD_ORDER:
            operation = methods.get(method)
            if not operation:
                continue
            summary = operation.get("summary") or operation.get("operationId", "")
            rows.setdefault(_group(path), []).append(
                f"| `{method.upper()}` | `{path}` | {summary} |"
            )
    lines = [
        "# SerialCuts HTTP API",
        "",
        "Сгенерировано из FastAPI-приложения командой `scripts/dump_openapi.py`.",
        "Полная схема — в [`openapi.json`](openapi.json). Не редактируйте этот файл вручную.",
        "",
    ]
    for group in sorted(rows):
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| Метод | Путь | Описание |")
        lines.append("| --- | --- | --- |")
        lines.extend(rows[group])
        lines.append("")
    return "\n".join(lines)


def write_docs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    schema = build_openapi()
    OPENAPI_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MARKDOWN_PATH.write_text(build_markdown(schema) + "\n", encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH.relative_to(PROJECT_ROOT)} and {MARKDOWN_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    write_docs()
