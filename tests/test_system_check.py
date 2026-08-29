from __future__ import annotations

from pathlib import Path

from app.application.system_check import run_system_check
from app.infrastructure.config import Settings


def test_system_check_reports_missing_ffmpeg_without_crashing(tmp_path: Path):
    settings = Settings(
        ffmpeg_path="definitely-missing-ffmpeg",
        ffprobe_path="definitely-missing-ffprobe",
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
    )

    report = run_system_check(settings)

    assert report.ok is False
    assert any(item.name == "ffmpeg" and not item.ok for item in report.items)

