from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.infrastructure.config import Settings
from app.models.entities import AppSetting


SETTINGS_KEY = "ui_settings"


class RuntimeSettings(BaseModel):
    cache_dir: Path
    output_dir: Path
    quality_profile: Literal["fast", "balanced", "quality"]
    min_clip_seconds: int = Field(ge=5, le=300)
    max_clip_seconds: int = Field(ge=5, le=300)
    auto_mode_enabled: bool
    background_queue_enabled: bool
    auto_score_threshold: int = Field(ge=0, le=100)
    max_clips_per_episode: int = Field(ge=1, le=20)
    render_preset: Literal["youtube_shorts", "instagram_reels"]
    render_use_nvenc: bool
    render_loudnorm_two_pass: bool
    subtitle_font_name: str = Field(min_length=1, max_length=128)
    subtitle_font_size: int = Field(ge=24, le=96)
    subtitle_safe_zone: Literal["standard", "shorts", "reels", "high"]
    subtitle_show_speaker_names: bool
    export_filename_template: str = Field(min_length=1, max_length=160)
    asr_adapter: Literal["stub", "faster-whisper"]
    llm_adapter: Literal["stub", "llama-cpp-http"]
    llm_base_url: str

    @field_validator("max_clip_seconds")
    @classmethod
    def max_after_min(cls, value: int, info) -> int:
        min_value = info.data.get("min_clip_seconds", 5)
        if value < min_value:
            raise ValueError("max_clip_seconds must be >= min_clip_seconds")
        return value


def runtime_settings_from_env(settings: Settings) -> RuntimeSettings:
    return RuntimeSettings(
        cache_dir=settings.cache_dir,
        output_dir=settings.output_dir,
        quality_profile=settings.quality_profile,
        min_clip_seconds=settings.min_clip_seconds,
        max_clip_seconds=settings.max_clip_seconds,
        auto_mode_enabled=settings.auto_mode_enabled,
        background_queue_enabled=settings.background_queue_enabled,
        auto_score_threshold=settings.auto_score_threshold,
        max_clips_per_episode=settings.max_clips_per_episode,
        render_preset=settings.render_preset,
        render_use_nvenc=settings.render_use_nvenc,
        render_loudnorm_two_pass=settings.render_loudnorm_two_pass,
        subtitle_font_name=settings.subtitle_font_name,
        subtitle_font_size=settings.subtitle_font_size,
        subtitle_safe_zone=settings.subtitle_safe_zone,
        subtitle_show_speaker_names=settings.subtitle_show_speaker_names,
        export_filename_template=settings.export_filename_template,
        asr_adapter=settings.asr_adapter,
        llm_adapter=settings.llm_adapter,
        llm_base_url=settings.llm_base_url,
    )


def get_runtime_settings(session: Session, env_settings: Settings) -> RuntimeSettings:
    defaults = runtime_settings_from_env(env_settings)
    stored = session.get(AppSetting, SETTINGS_KEY)
    if stored is None:
        return defaults
    return defaults.model_copy(update=stored.value_json)


def save_runtime_settings(session: Session, payload: RuntimeSettings) -> RuntimeSettings:
    setting = session.get(AppSetting, SETTINGS_KEY)
    data = payload.model_dump(mode="json")
    if setting is None:
        session.add(AppSetting(key=SETTINGS_KEY, value_json=data))
    else:
        setting.value_json = data
    session.flush()
    return payload


def effective_settings(session: Session, env_settings: Settings) -> Settings:
    runtime = get_runtime_settings(session, env_settings)
    return env_settings.model_copy(
        update={
            "cache_dir": runtime.cache_dir,
            "output_dir": runtime.output_dir,
            "quality_profile": runtime.quality_profile,
            "min_clip_seconds": runtime.min_clip_seconds,
            "max_clip_seconds": runtime.max_clip_seconds,
            "auto_mode_enabled": runtime.auto_mode_enabled,
            "background_queue_enabled": runtime.background_queue_enabled,
            "auto_score_threshold": runtime.auto_score_threshold,
            "max_clips_per_episode": runtime.max_clips_per_episode,
            "render_preset": runtime.render_preset,
            "render_use_nvenc": runtime.render_use_nvenc,
            "render_loudnorm_two_pass": runtime.render_loudnorm_two_pass,
            "subtitle_font_name": runtime.subtitle_font_name,
            "subtitle_font_size": runtime.subtitle_font_size,
            "subtitle_safe_zone": runtime.subtitle_safe_zone,
            "subtitle_show_speaker_names": runtime.subtitle_show_speaker_names,
            "export_filename_template": runtime.export_filename_template,
            "asr_adapter": runtime.asr_adapter,
            "llm_adapter": runtime.llm_adapter,
            "llm_base_url": runtime.llm_base_url,
        }
    )
