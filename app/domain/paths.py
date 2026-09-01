from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi"}


def normalize_local_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


class PathOutsideAllowedRootsError(ValueError):
    """Raised when a resolved path escapes every allowed root directory."""


def resolve_within(value: str | Path, allowed_roots: Iterable[str | Path]) -> Path:
    """Resolve ``value`` and guarantee it stays inside one of ``allowed_roots``.

    Guards file-serving endpoints: even though stored paths are written by the
    app itself, a future bug or a hand-edited database row must not be able to
    stream an arbitrary file from disk.
    """
    resolved = normalize_local_path(value)
    roots = [normalize_local_path(root) for root in allowed_roots]
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise PathOutsideAllowedRootsError(
        f"Путь вне разрешённых каталогов SerialCuts: {resolved}"
    )


def is_supported_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS

