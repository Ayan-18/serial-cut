from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SERIALCUTS_", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8090
    database_url: str = "sqlite:///./data/serialcuts.db"
    cache_dir: Path = Path("./data/cache")
    output_dir: Path = Path("./data/output")
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    proxy_width: int = 640
    proxy_crf: int = 28
    asr_adapter: Literal["stub", "faster-whisper"] = "stub"
    asr_model_name: str = "small"
    asr_device: Literal["auto", "cuda", "cpu"] = "auto"
    asr_compute_type: str = "int8_float16"
    asr_fallback_compute_type: str = "int8"
    llm_adapter: Literal["stub", "llama-cpp-http"] = "stub"
    llm_base_url: str = "http://127.0.0.1:8081"
    llm_model_hint: str = "Qwen3-8B-Instruct-GGUF-Q4"
    quality_profile: Literal["fast", "balanced", "quality"] = "balanced"
    min_clip_seconds: int = 35
    max_clip_seconds: int = 59
    auto_score_threshold: int = 82
    max_clips_per_episode: int = 3
    auto_mode_enabled: bool = False
    render_preset: Literal["youtube_shorts", "instagram_reels"] = "youtube_shorts"
    render_use_nvenc: bool = False
    render_loudnorm_two_pass: bool = False
    subtitle_font_name: str = "Segoe UI"
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        raise TypeError("telegram_allowed_user_ids must be a comma-separated string or list")

    @field_validator("max_clip_seconds")
    @classmethod
    def validate_duration_range(cls, value: int, info) -> int:
        min_value = info.data.get("min_clip_seconds", 35)
        if value < min_value:
            raise ValueError("max_clip_seconds must be greater than or equal to min_clip_seconds")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
