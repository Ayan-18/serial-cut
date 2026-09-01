from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.application.settings import effective_settings, get_runtime_settings, save_runtime_settings
from app.infrastructure.config import Settings


def test_runtime_settings_persist_ui_overrides(session, tmp_path: Path):
    defaults = Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out")
    runtime = get_runtime_settings(session, defaults)
    updated = runtime.model_copy(
        update={"auto_mode_enabled": True, "auto_score_threshold": 91, "subtitle_font_size": 42}
    )

    save_runtime_settings(session, updated)
    session.commit()
    loaded = get_runtime_settings(session, defaults)

    assert loaded.auto_mode_enabled is True
    assert loaded.auto_score_threshold == 91
    assert loaded.subtitle_font_size == 42


def test_effective_settings_keep_env_tools_and_apply_ui_overrides(session, tmp_path: Path):
    env = Settings(
        ffmpeg_path="custom-ffmpeg",
        ffprobe_path="custom-ffprobe",
        asr_adapter="faster-whisper",
        llm_adapter="llama-cpp-http",
        llm_base_url="http://127.0.0.1:8081",
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
    )
    save_runtime_settings(
        session,
        get_runtime_settings(session, env).model_copy(
            update={
                "render_use_nvenc": True,
                "asr_adapter": "stub",
                "llm_adapter": "stub",
                "llm_base_url": "http://stale-setting.invalid",
            }
        ),
    )

    merged = effective_settings(session, env)

    assert merged.ffmpeg_path == "custom-ffmpeg"
    assert merged.ffprobe_path == "custom-ffprobe"
    assert merged.asr_adapter == "faster-whisper"
    assert merged.llm_adapter == "llama-cpp-http"
    assert merged.llm_base_url == "http://127.0.0.1:8081"
    assert merged.render_use_nvenc is True


def test_settings_parse_empty_and_csv_telegram_user_ids_from_dotenv(tmp_path: Path):
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("SERIALCUTS_TELEGRAM_ALLOWED_USER_IDS=\n", encoding="utf-8")
    csv_env = tmp_path / "csv.env"
    csv_env.write_text("SERIALCUTS_TELEGRAM_ALLOWED_USER_IDS=111, 222\n", encoding="utf-8")

    assert Settings(_env_file=empty_env).telegram_allowed_user_ids == []
    assert Settings(_env_file=csv_env).telegram_allowed_user_ids == [111, 222]


def test_llm_endpoint_is_limited_to_this_computer():
    assert Settings(llm_base_url="http://localhost:8081/").llm_base_url == "http://localhost:8081"
    assert Settings(llm_base_url="http://127.0.0.2:8081").llm_base_url == "http://127.0.0.2:8081"
    assert Settings(llm_base_url="http://[::1]:8081").llm_base_url == "http://[::1]:8081"

    with pytest.raises(ValidationError, match="localhost/loopback"):
        Settings(llm_base_url="https://models.example.com/v1")
    with pytest.raises(ValidationError, match="логин или пароль"):
        Settings(llm_base_url="http://user:secret@127.0.0.1:8081")
