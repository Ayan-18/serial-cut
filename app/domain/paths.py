from __future__ import annotations

from pathlib import Path


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi"}


def normalize_local_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def is_supported_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS

