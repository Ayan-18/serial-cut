from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


def canonical_render_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def source_signature(path: Path) -> dict[str, int | str | None]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "size": None, "modified_ns": None}
    return {"path": str(path), "size": stat.st_size, "modified_ns": stat.st_mtime_ns}


def small_file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
