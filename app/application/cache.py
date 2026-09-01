from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CACHE_MARKER = ".serialcuts-cache"
CACHE_MARKER_CONTENT = "SerialCuts managed cache v1\n"


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
        if path.name != CACHE_MARKER and path.is_file() and not path.is_symlink():
            files += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    return CacheSummary(str(root), files, total_bytes)


def prepare_cache_directory(
    cache_dir: Path,
    *,
    protected_paths: list[Path] | None = None,
    allow_existing_unmarked: bool = False,
) -> Path:
    """Create/mark a dedicated cache directory after rejecting dangerous paths."""
    root = cache_dir.expanduser().resolve(strict=False)
    _validate_cache_root(root, protected_paths or [])
    marker = root / CACHE_MARKER
    if marker.exists():
        if not marker.is_file() or marker.read_text(encoding="utf-8") != CACHE_MARKER_CONTENT:
            raise ValueError("Маркер каталога кэша повреждён")
        return root
    if root.exists():
        existing = [item for item in root.iterdir()]
        if existing and not allow_existing_unmarked:
            raise ValueError(
                "Выбранная папка не является кэшем SerialCuts. Укажите новую пустую папку."
            )
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(CACHE_MARKER_CONTENT, encoding="utf-8")
    return root


def clear_cache(
    cache_dir: Path,
    *,
    confirmed: bool,
    protected_paths: list[Path] | None = None,
) -> CacheSummary:
    if not confirmed:
        raise ValueError("Для очистки кэша требуется явное подтверждение")
    root = cache_dir.expanduser().resolve(strict=False)
    if not root.exists():
        raise ValueError("Каталог кэша не существует")
    _validate_cache_root(root, protected_paths or [])
    marker = root / CACHE_MARKER
    if not marker.is_file() or marker.read_text(encoding="utf-8") != CACHE_MARKER_CONTENT:
        raise ValueError("Очистка разрешена только для папки с маркером .serialcuts-cache")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path == marker:
            continue
        if path.is_symlink():
            path.unlink(missing_ok=True)
            continue
        resolved = path.resolve(strict=False)
        if root not in resolved.parents:
            raise ValueError(f"Путь выходит за каталог кэша: {path}")
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return cache_summary(root)


def _validate_cache_root(root: Path, protected_paths: list[Path]) -> None:
    if root == root.parent or root == Path.home().resolve(strict=False):
        raise ValueError("Небезопасный путь кэша")
    for protected in protected_paths:
        target = protected.expanduser().resolve(strict=False)
        if root == target or root in target.parents:
            raise ValueError(f"Каталог кэша может затронуть защищённый путь: {target}")
