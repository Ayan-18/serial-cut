from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SERIALCUTS_", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8090
    database_url: str = "sqlite:///./data/serialcuts.db"
    cache_dir: Path = Path("./data/cache")
    output_dir: Path = Path("./data/output")
    characters_dir: Path = Path("./data/characters")
    face_detector_model: Path = Path("./data/models/face/face_detection_yunet_2026may.onnx")
    face_recognizer_model: Path = Path("./data/models/face/face_recognition_sface_2021dec.onnx")
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
    background_queue_enabled: bool = False
    render_preset: Literal["youtube_shorts", "instagram_reels"] = "youtube_shorts"
    render_use_nvenc: bool = False
    render_loudnorm_two_pass: bool = False
    subtitle_font_name: str = "Segoe UI"
    subtitle_font_size: int = Field(default=48, ge=24, le=96)
    subtitle_safe_zone: Literal["standard", "shorts", "reels", "high"] = "shorts"
    subtitle_show_speaker_names: bool = False
    export_filename_template: str = "{episode}_clip-{candidate}_{title}_score-{score}"
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

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        return validate_loopback_http_url(value)


def validate_loopback_http_url(value: str) -> str:
    """Keep transcript-bearing model requests on this computer."""
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM URL должен быть полным HTTP(S)-адресом")
    hostname = parsed.hostname.casefold()
    if hostname != "localhost":
        try:
            if not ip_address(hostname).is_loopback:
                raise ValueError("LLM URL должен вести только на localhost/loopback")
        except ValueError as exc:
            if "loopback" in str(exc):
                raise
            raise ValueError("LLM URL должен вести только на localhost/loopback") from exc
    if parsed.username or parsed.password:
        raise ValueError("LLM URL не должен содержать логин или пароль")
    return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
