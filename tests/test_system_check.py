from __future__ import annotations

from pathlib import Path

from app.application.system_check import OPTIONAL_CHECKS, run_system_check
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


def test_system_check_includes_advisory_windows_diagnostics(tmp_path: Path):
    settings = Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out")

    report = run_system_check(settings)
    names = {item.name for item in report.items}

    assert {"virtualenv", "node", "llama-server", "long_paths"} <= names
    # Advisory checks must never flip the overall required status.
    failing_required = [
        item for item in report.items if not item.ok and item.name not in OPTIONAL_CHECKS
    ]
    assert report.ok == (not failing_required)

