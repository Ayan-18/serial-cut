from __future__ import annotations

from datetime import datetime

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
    created_at: datetime
    updated_at: datetime


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
    crop_offset_x: float
    crop_scale: float
    crop_keyframes_json: list
    thumbnail_path: str | None
    status: str
    story_order: int | None = None
    story_role: str | None = None
    continuity_note: str | None = None


class StoryContextRead(BaseModel):
    season_id: int
    episode_id: int
    season_context: str
    episode_summary: str
    required_events: list[str]
    excluded_events: list[str]
    spoilers_allowed: bool
    candidate_mode: str


class StoryContextUpdate(BaseModel):
    season_context: str = Field(default="", max_length=8000)
    episode_summary: str = Field(default="", max_length=8000)
    required_events: list[str] = Field(default_factory=list, max_length=30)
    excluded_events: list[str] = Field(default_factory=list, max_length=30)
    spoilers_allowed: bool = True
    candidate_mode: str = Field(default="highlights", pattern="^(highlights|story)$")


class StoryArcCreateRequest(BaseModel):
    season_id: int
    title: str | None = Field(default=None, max_length=255)
    prompt: str = Field(default="", max_length=2000)
    arc_type: str = Field(default="custom", pattern="^(custom|character|story_arc)$")
    output_format: str = Field(default="shorts_series", pattern="^(single_short|shorts_series|story_video|long_video)$")
    target_character_id: int | None = None
    max_segments: int = Field(default=8, ge=1, le=40)
    max_duration_seconds: int = Field(default=420, ge=15, le=7200)


class StoryArcSegmentRead(BaseModel):
    id: int
    story_arc_id: int
    episode_id: int
    episode_file_name: str
    candidate_id: int | None
    candidate_score: int | None
    sort_order: int
    start_time: float
    end_time: float
    title: str
    note: str
    role: str | None


class StoryArcExportRead(BaseModel):
    id: int
    story_arc_id: int
    output_path: str
    metadata_path: str | None
    cover_path: str | None
    width: int
    height: int
    include_subtitles: bool
    preset_name: str
    segment_count: int
    status: str


class StoryArcRead(BaseModel):
    id: int
    season_id: int
    season_title: str
    title: str
    prompt: str
    arc_type: str
    output_format: str
    target_character_id: int | None
    target_character_name: str | None
    status: str
    total_duration_seconds: float
    plan_json: dict
    segments: list[StoryArcSegmentRead]
    exports: list[StoryArcExportRead]


class StoryArcRenderRequest(BaseModel):
    include_subtitles: bool = True
    use_nvenc: bool | None = None
    preset_name: str | None = Field(default=None, pattern="^(youtube_shorts|instagram_reels)$")
    loudnorm_two_pass: bool | None = None
    force_rerender: bool = False
    transition_style: str = Field(default="cut", pattern="^(cut|fade)$")


class StoryArcRenderResponse(BaseModel):
    story_arc_id: int
    export_id: int
    output_path: str
    metadata_path: str | None
    cover_path: str | None
    segment_count: int
    duration_seconds: float


class StoryArcRenderJobResponse(BaseModel):
    job: JobRead


class StoryArcUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    prompt: str | None = Field(default=None, max_length=2000)
    output_format: str | None = Field(default=None, pattern="^(single_short|shorts_series|story_video|long_video)$")
    status: str | None = Field(default=None, pattern="^(draft|ready|rendered|archived)$")
    narration: list[dict] | None = None


class StoryArcSegmentUpdateRequest(BaseModel):
    sort_order: int | None = Field(default=None, ge=1, le=200)
    start_time: float | None = Field(default=None, ge=0)
    end_time: float | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=64)


class StoryArcCandidateAddRequest(BaseModel):
    candidate_id: int


class NarrationRead(BaseModel):
    story_arc_id: int
    text: str
    lines: list[dict]


class NarrationAudioRead(BaseModel):
    story_arc_id: int
    audio_path: str
    script_path: str


class VideoScriptCreateRequest(BaseModel):
    season_id: int
    story_arc_id: int | None = None
    title: str | None = Field(default=None, max_length=255)
    prompt: str = Field(default="", max_length=2000)
    style: str = Field(default="chronological", pattern="^(chronological|documentary|dynamic|key_moments)$")


class VideoScriptUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    script_text: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, pattern="^(draft|ready|archived)$")


class VideoScriptRead(BaseModel):
    id: int
    season_id: int
    story_arc_id: int | None
    title: str
    prompt: str
    style: str
    script_text: str
    structure_json: dict
    status: str


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


class ProjectDiagnosticCheckRead(BaseModel):
    name: str
    ok: bool
    message: str


class ProjectDiagnosticsRead(BaseModel):
    checks: list[ProjectDiagnosticCheckRead]
    recommendations: list[str]
    counts: dict[str, int]


class EpisodeOutlineRead(BaseModel):
    episode_id: int
    summary_json: dict


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    color: str = Field(default="#b9ddff", pattern="^#[0-9a-fA-F]{6}$")
    photo_data_url: str | None = Field(default=None, max_length=12_000_000)


class CharacterPhotoAdd(BaseModel):
    photo_data_url: str = Field(min_length=1, max_length=12_000_000)


class CharacterMergeRequest(BaseModel):
    target_character_id: int


class CharacterRead(BaseModel):
    id: int
    season_id: int
    name: str
    description: str
    aliases: list[str]
    color: str
    photo_count: int
    photo_urls: list[str]
    voice_sample_count: int


class SpeakerIdentityUpdate(BaseModel):
    source_label: str = Field(min_length=1, max_length=64)
    character_id: int


class SpeakerIdentityRead(BaseModel):
    source_label: str
    character_id: int
    character_name: str
    confidence: float | None = None
    method: str


class SpeakerLabelsRead(BaseModel):
    labels: list[str]


class CharacterRecognitionResponse(BaseModel):
    analyzed_labels: int
    assigned_labels: int
    assignments: list[SpeakerIdentityRead]
    face_model: str
    voice_profiles_used: int


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    adjusted_start_time: float | None = None
    adjusted_end_time: float | None = None
    crop_mode: str | None = Field(default=None, pattern="^(auto-follow|center-crop|blurred-background)$")
    crop_offset_x: float | None = Field(default=None, ge=-1, le=1)
    crop_scale: float | None = Field(default=None, ge=1, le=2)
    reason: str | None = None


class CandidateEditRequest(BaseModel):
    adjusted_start_time: float | None = None
    adjusted_end_time: float | None = None
    crop_mode: str | None = Field(default=None, pattern="^(auto-follow|center-crop|blurred-background)$")
    crop_offset_x: float | None = Field(default=None, ge=-1, le=1)
    crop_scale: float | None = Field(default=None, ge=1, le=2)


class CandidateEditResponse(BaseModel):
    candidate_id: int
    status: str


class ReviewResponse(BaseModel):
    candidate_id: int
    status: str
    decision_id: int


class RenderRequest(BaseModel):
    include_subtitles: bool = True
    use_nvenc: bool | None = None
    preset_name: str | None = Field(default=None, pattern="^(youtube_shorts|instagram_reels)$")
    loudnorm_two_pass: bool | None = None
    force_rerender: bool = False


class CandidateSubtitlePayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=500)
    speaker_label: str | None = Field(default=None, max_length=64)


class CandidateSubtitlesUpdate(BaseModel):
    subtitles: list[CandidateSubtitlePayload] = Field(max_length=200)


class SubtitleQualityRead(BaseModel):
    candidate_id: int
    rows: int
    warnings: list[str]
    long_rows: int
    overlaps: int
    too_fast_rows: int


class AutoCropResponse(BaseModel):
    candidate_id: int
    crop_offset_x: float
    faces_detected: int
    frames_sampled: int
    keyframes: list[dict]
    active_speaker_frames: int
    identified_speaker_frames: int
    lip_motion_frames: int
    face_model: str


class RenderResponse(BaseModel):
    candidate_id: int
    export_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None


class PreviewRenderResponse(BaseModel):
    candidate_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None
    duration_seconds: float
    preview_url: str


class RenderJobResponse(BaseModel):
    job: JobRead


class CacheRead(BaseModel):
    cache_dir: str
    files: int
    bytes: int


class CacheClearRequest(BaseModel):
    confirm: bool = False


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
    face_ready: bool
    face_model: str
    face_detector_path: str
    face_recognizer_path: str
    face_detector_exists: bool
    face_recognizer_exists: bool
    details: list[str]
    recommendations: list[str]


class JobStageRetryRequest(BaseModel):
    stage_name: str = Field(pattern="^(stage2_media|stage3_candidates|auto_export|render_clip|render_story_arc)$")


class CandidateQualityRead(BaseModel):
    candidate_id: int
    duration_seconds: float
    final_score: int
    boundary_score: int
    standalone_score: int
    payoff_score: int
    audio_score: int
    visual_score: int
    problems: list[str]
    recommendations: list[str]


class EpisodeQualityRead(BaseModel):
    episode_id: int
    stage: str
    transcript_segments: int
    words: int
    scenes: int
    candidates: int
    approved: int
    rejected: int
    rendered: int
    average_score: int
    problem_candidates: int
    top_problems: list[str]


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
    include_subtitles: bool
    preset_name: str
    status: str


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


class JobStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    name: str
    status: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    artifact_path: str | None
