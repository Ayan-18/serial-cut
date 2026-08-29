from __future__ import annotations

from pathlib import Path

from app.application.settings import effective_settings, get_runtime_settings, save_runtime_settings
from app.infrastructure.config import Settings


def test_runtime_settings_persist_ui_overrides(session, tmp_path: Path):
    defaults = Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out")
    runtime = get_runtime_settings(session, defaults)
    updated = runtime.model_copy(update={"auto_mode_enabled": True, "auto_score_threshold": 91})

    save_runtime_settings(session, updated)
    session.commit()
    loaded = get_runtime_settings(session, defaults)

    assert loaded.auto_mode_enabled is True
    assert loaded.auto_score_threshold == 91


def test_effective_settings_keep_env_tools_and_apply_ui_overrides(session, tmp_path: Path):
    env = Settings(
        ffmpeg_path="custom-ffmpeg",
        ffprobe_path="custom-ffprobe",
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
    )
    save_runtime_settings(session, get_runtime_settings(session, env).model_copy(update={"render_use_nvenc": True}))

    merged = effective_settings(session, env)

    assert merged.ffmpeg_path == "custom-ffmpeg"
    assert merged.ffprobe_path == "custom-ffprobe"
    assert merged.render_use_nvenc is True
