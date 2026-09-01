from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.domain.paths import PathOutsideAllowedRootsError, resolve_within
from app.infrastructure.config import Settings

logger = logging.getLogger(__name__)


def served_media_roots(settings: Settings) -> list[Path]:
    """Directories SerialCuts is allowed to stream generated files from."""
    return [settings.output_dir, settings.cache_dir]


def safe_file_response(
    settings: Settings,
    stored_path: str | None,
    *,
    media_type: str,
    missing_detail: str,
    filename: str | None = None,
) -> FileResponse:
    """Serve a generated file only if it resolves inside an allowed output root.

    Stored paths are written by the app itself, but a stale or hand-edited
    database row must never be able to stream an arbitrary file from disk.
    """
    if not stored_path:
        raise HTTPException(status_code=404, detail=missing_detail)
    try:
        path = resolve_within(stored_path, served_media_roots(settings))
    except PathOutsideAllowedRootsError as exc:
        logger.warning("Blocked out-of-tree file request: %s", exc)
        raise HTTPException(status_code=404, detail=missing_detail) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail=missing_detail)
    return FileResponse(path, media_type=media_type, filename=filename or path.name)
