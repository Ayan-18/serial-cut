from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CacheSummary:
    cache_dir: str
    files: int
    bytes: int


def cache_summary(cache_dir: Path) -> CacheSummary:
    root = cache_dir.expanduser().resolve(strict=False)
    if not root.exists():
        return CacheSummary(str(root), 0, 0)
    files = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    return CacheSummary(str(root), files, total_bytes)


def clear_cache(cache_dir: Path, *, confirmed: bool) -> CacheSummary:
    if not confirmed:
        raise ValueError("Для очистки кэша требуется явное подтверждение")
    root = cache_dir.expanduser().resolve(strict=False)
    if not root.exists():
        return cache_summary(root)
    if root == root.parent:
        raise ValueError("Небезопасный путь кэша")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        resolved = path.resolve(strict=False)
        if root not in resolved.parents:
            raise ValueError(f"Путь выходит за каталог кэша: {path}")
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return cache_summary(root)
