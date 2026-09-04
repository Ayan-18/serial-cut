from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RuntimeSettingsRead(BaseModel):
    cache_dir: str
    output_dir: str
    quality_profile: str
    min_clip_seconds: int
    max_clip_seconds: int
    auto_mode_enabled: bool
    background_queue_enabled: bool
    auto_score_threshold: int
    max_clips_per_episode: int
    render_preset: str
    render_use_nvenc: bool
    render_loudnorm_two_pass: bool
    subtitle_font_name: str
    subtitle_font_size: int
    subtitle_safe_zone: str
    subtitle_show_speaker_names: bool
    export_filename_template: str
    tts_adapter: str
    tts_narrator_voice: str
    asr_adapter: str
    llm_adapter: str
    llm_base_url: str


class SearchResultRead(BaseModel):
    kind: str
    episode_id: int
    episode_file_name: str
    candidate_id: int | None
    start_time: float
    end_time: float
    title: str
    snippet: str
    score: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultRead]


class PublishingPlanCreateRequest(BaseModel):
    season_id: int
    story_arc_id: int | None = None
    story_arc_export_id: int | None = None
    platform: str = Field(default="youtube_shorts", pattern="^(youtube_shorts|instagram_reels|tiktok|vk_clips)$")
    scheduled_for: datetime | None = None


class PublishingPlanUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    hashtags: list[str] | None = Field(default=None, max_length=40)
    scheduled_for: datetime | None = None
    status: str | None = Field(default=None, pattern="^(draft|ready|scheduled|published|archived)$")


class PublishingPlanRead(BaseModel):
    id: int
    season_id: int
    story_arc_id: int | None
    story_arc_export_id: int | None
    platform: str
    title: str
    description: str
    hashtags: list[str]
    scheduled_for: datetime | None
    status: str


class PublishingPackageRead(BaseModel):
    plan_id: int
    manifest_path: str


class ProjectDiagnosticCheckRead(BaseModel):
    name: str
    ok: bool
    message: str


class ProjectDiagnosticsRead(BaseModel):
    checks: list[ProjectDiagnosticCheckRead]
    recommendations: list[str]
    counts: dict[str, int]


class ModelCatalogEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    title: str
    purpose: str
    approx_size_mb: int
    target_dir: str
    installed: bool
    files_present: list[str]
    files_missing: list[str]
    installable_in_app: bool
    install_command: str


class ModelInstallRequest(BaseModel):
    confirm: bool = False


class ModelInstallProgressRead(BaseModel):
    key: str
    status: str  # idle | running | done | error
    received_bytes: int = 0
    total_bytes: int = 0
    detail: str = ""


class ModelDiagnosticsRead(BaseModel):
    asr_adapter: str
    asr_ready: bool
    asr_model: str
    asr_device: str
    asr_compute_type: str
    asr_package_installed: bool
    asr_local_model_path: str | None
    asr_local_model_exists: bool
    llm_adapter: str
    llm_ready: bool
    llm_url: str
    llm_model_hint: str
    llm_latency_ms: int | None
    tts_adapter: str
    tts_ready: bool
    tts_model_path: str
    tts_model_exists: bool
    tts_torch_installed: bool
    tts_narrator_voice: str
    face_ready: bool
    face_model: str
    face_detector_path: str
    face_recognizer_path: str
    face_detector_exists: bool
    face_recognizer_exists: bool
    details: list[str]
    recommendations: list[str]


class CacheRead(BaseModel):
    cache_dir: str
    files: int
    bytes: int


class CacheClearRequest(BaseModel):
    confirm: bool = False


__all__ = [
    "RuntimeSettingsRead",
    "SearchResultRead",
    "SearchResponse",
    "PublishingPlanCreateRequest",
    "PublishingPlanUpdateRequest",
    "PublishingPlanRead",
    "PublishingPackageRead",
    "ProjectDiagnosticCheckRead",
    "ProjectDiagnosticsRead",
    "ModelCatalogEntryRead",
    "ModelInstallProgressRead",
    "ModelInstallRequest",
    "ModelDiagnosticsRead",
    "CacheRead",
    "CacheClearRequest",
]
