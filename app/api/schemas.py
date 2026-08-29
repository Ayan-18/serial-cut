from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SeasonImportRequest(BaseModel):
    root_path: str = Field(min_length=1)
    title: str | None = None


class EpisodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_path: str
    stage: str
    size_bytes: int
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None


class SeasonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    root_path: str
    episodes: list[EpisodeRead]


class RuntimeSettingsRead(BaseModel):
    cache_dir: str
    output_dir: str
    quality_profile: str
    min_clip_seconds: int
    max_clip_seconds: int
    auto_mode_enabled: bool
    auto_score_threshold: int
    max_clips_per_episode: int
    render_preset: str
    render_use_nvenc: bool
    render_loudnorm_two_pass: bool
    subtitle_font_name: str
    asr_adapter: str
    llm_adapter: str
    llm_base_url: str


class ImportResponse(BaseModel):
    season_id: int
    created: int
    skipped_duplicates: int
    episode_ids: list[int]


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int | None
    kind: str
    status: str
    current_stage: str | None
    progress: float
    error_message: str | None


class Stage2RunResponse(BaseModel):
    episode_id: int
    stage: str
    audio_path: str | None
    proxy_path: str | None
    transcript_segments: int
    scenes: int


class Stage3RunResponse(BaseModel):
    episode_id: int
    stage: str
    outline_created: bool
    candidates: int


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int
    start_time: float
    end_time: float
    title: str
    description: str
    moment_type: str
    score: int
    scores_json: dict
    rationale: str
    problems_json: list
    crop_mode: str
    status: str


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    adjusted_start_time: float | None = None
    adjusted_end_time: float | None = None
    crop_mode: str | None = Field(default=None, pattern="^(auto-follow|center-crop|blurred-background)$")
    reason: str | None = None


class ReviewResponse(BaseModel):
    candidate_id: int
    status: str
    decision_id: int


class RenderRequest(BaseModel):
    include_subtitles: bool = True
    use_nvenc: bool | None = None
    preset_name: str | None = Field(default=None, pattern="^(youtube_shorts|instagram_reels)$")
    loudnorm_two_pass: bool | None = None


class RenderResponse(BaseModel):
    candidate_id: int
    export_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None


class ExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    output_path: str
    metadata_path: str | None
    subtitle_path: str | None
    cover_path: str | None
    width: int
    height: int


class AutoExportRequest(BaseModel):
    threshold: int | None = Field(default=None, ge=0, le=100)
    max_clips: int | None = Field(default=None, ge=1, le=20)
    use_nvenc: bool | None = None


class AutoExportResponse(BaseModel):
    approved: int
    rendered: int
    skipped: int
    export_paths: list[str]


class EnqueueSeasonRequest(BaseModel):
    auto: bool = False


class QueueRunResponse(BaseModel):
    ran: bool
    job_id: int | None
    status: str
    message: str


class QueueStateResponse(BaseModel):
    state: str
