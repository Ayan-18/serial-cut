from __future__ import annotations

import importlib.util
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "dump_openapi", _PROJECT_ROOT / "scripts" / "dump_openapi.py"
)
dump_openapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dump_openapi)  # type: ignore[union-attr]

_REGEN_HINT = "Запустите .\\.venv\\Scripts\\python.exe scripts\\dump_openapi.py и закоммитьте docs/."


def test_api_markdown_is_in_sync_with_the_app():
    schema = dump_openapi.build_openapi()
    expected = dump_openapi.build_markdown(schema) + "\n"
    actual = (_PROJECT_ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    assert actual == expected, _REGEN_HINT


def test_every_api_route_is_documented():
    schema = dump_openapi.build_openapi()
    documented = (_PROJECT_ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    for path in schema.get("paths", {}):
        assert f"`{path}`" in documented, f"{path} отсутствует в docs/API.md. {_REGEN_HINT}"
