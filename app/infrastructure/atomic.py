from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def temp_sibling(final_path: Path) -> Path:
    return final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")


def replace_atomically(temp_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.replace(final_path)

