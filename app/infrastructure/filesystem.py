from __future__ import annotations

from pathlib import Path

from app.domain.paths import is_supported_video, normalize_local_path


def discover_video_files(root_path: str | Path) -> list[Path]:
    root = normalize_local_path(root_path)
    if not root.exists():
        raise FileNotFoundError(f"Папка не найдена: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Ожидалась папка сезона: {root}")
    return sorted(path for path in root.rglob("*") if is_supported_video(path))

