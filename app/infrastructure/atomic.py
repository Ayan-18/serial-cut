from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def temp_sibling(final_path: Path) -> Path:
    """A short unique sibling in the same directory for an atomic write.

    The name is deliberately independent of ``final_path.name``: embedding a long
    export filename here used to push the temp path past the Windows MAX_PATH
    (260) limit even when the final file itself fit. Callers that need a specific
    extension add it with ``.with_suffix(...)``.
    """
    return final_path.with_name(f".{uuid4().hex[:16]}.tmp")


def replace_atomically(temp_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.replace(final_path)


def write_text_atomically(final_path: Path, content: str, encoding: str = "utf-8") -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = temp_sibling(final_path)
    try:
        temp_path.write_text(content, encoding=encoding)
        replace_atomically(temp_path, final_path)
    finally:
        temp_path.unlink(missing_ok=True)

