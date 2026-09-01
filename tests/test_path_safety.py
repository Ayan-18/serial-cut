from __future__ import annotations

from pathlib import Path

import pytest

from app.api.media_files import safe_file_response, served_media_roots
from app.domain.paths import PathOutsideAllowedRootsError, resolve_within
from app.infrastructure.config import Settings
from fastapi import HTTPException


def _settings(tmp_path: Path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out")


def test_resolve_within_accepts_files_inside_roots(tmp_path: Path):
    root = tmp_path / "out"
    target = root / "ep" / "clip.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")

    assert resolve_within(str(target), [root]) == target.resolve()


def test_resolve_within_rejects_traversal_outside_roots(tmp_path: Path):
    root = tmp_path / "out"
    root.mkdir()
    escape = root / ".." / ".." / "windows" / "system32" / "config"

    with pytest.raises(PathOutsideAllowedRootsError):
        resolve_within(str(escape), [root])


def test_safe_file_response_hides_out_of_tree_paths(tmp_path: Path):
    settings = _settings(tmp_path)
    for root in served_media_roots(settings):
        root.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")

    with pytest.raises(HTTPException) as excinfo:
        safe_file_response(
            settings,
            str(secret),
            media_type="text/plain",
            missing_detail="Файл экспорта не найден",
        )
    assert excinfo.value.status_code == 404


def test_safe_file_response_serves_files_inside_output_dir(tmp_path: Path):
    settings = _settings(tmp_path)
    clip = settings.output_dir / "fp" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"video")

    response = safe_file_response(
        settings,
        str(clip),
        media_type="video/mp4",
        missing_detail="Файл экспорта не найден",
    )
    assert Path(response.path) == clip.resolve()
