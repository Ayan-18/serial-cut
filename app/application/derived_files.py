from __future__ import annotations

from pathlib import Path


def delete_derived_artifacts(paths: list[str | Path | None], allowed_roots: list[Path]) -> list[str]:
    """Delete only explicit derived artifacts contained by an approved cache/output root."""
    roots = [item.expanduser().resolve(strict=False) for item in allowed_roots]
    removed: list[str] = []
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve(strict=False)
        root = next((item for item in roots if item in path.parents), None)
        if root is None:
            continue
        if path.is_file() or path.is_symlink():
            try:
                path.unlink(missing_ok=True)
                removed.append(str(path))
            except OSError:
                continue
            _prune_empty_parents(path.parent, root)
    return removed


def delete_derived_tree(path: Path, allowed_roots: list[Path]) -> list[str]:
    root_path = path.expanduser().resolve(strict=False)
    roots = [item.expanduser().resolve(strict=False) for item in allowed_roots]
    allowed = next((item for item in roots if item in root_path.parents), None)
    if allowed is None or not root_path.exists():
        return []
    try:
        entries = list(root_path.rglob("*"))
    except OSError:
        return []
    files = [item for item in entries if item.is_file() or item.is_symlink()]
    removed = delete_derived_artifacts(files, roots)
    for directory in sorted(
        (item for item in entries if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        root_path.rmdir()
    except OSError:
        pass
    return removed


def _prune_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
