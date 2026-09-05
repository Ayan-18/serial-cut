from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import JobRead


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


class CandidateSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    edit_revision: int
    kind: str
    label: str
    created_at: datetime
    start_time: float
    end_time: float
    crop_mode: str
    subtitle_rows: int


class BatchReviewRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
    decision: str


class BatchRenderRequest(BaseModel):
    candidate_ids: list[int] = Field(min_length=1)
    include_subtitles: bool = True
    use_nvenc: bool | None = None
    preset_name: str | None = None
    loudnorm_two_pass: bool | None = None
    force_rerender: bool = False


class BatchOutcomeRead(BaseModel):
    requested: int
    succeeded: list[int]
    skipped: list[dict]
    job_ids: list[int]


class KeyframeInfoRead(BaseModel):
    index: int
    time: float
    url: str


class KeyframeStripRead(BaseModel):
    candidate_id: int
    edit_revision: int
    start_time: float
    end_time: float
    frames: list[KeyframeInfoRead]


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    adjusted_start_time: float | None = None
    adjusted_end_time: float | None = None
    crop_mode: str | None = Field(
        default=None, pattern="^(auto-follow|center-crop|blurred-background)$",
        description="Центр или По лицу: крупное видео занимает 2/3 высоты поверх размытого фона. blurred-background — совместимый псевдоним центра.",
    )
    crop_offset_x: float | None = Field(default=None, ge=-1, le=1)
    crop_scale: float | None = Field(default=None, ge=1, le=2)
    reason: str | None = None


class CandidateEditRequest(BaseModel):
    adjusted_start_time: float | None = None
    adjusted_end_time: float | None = None
    crop_mode: str | None = Field(
        default=None, pattern="^(auto-follow|center-crop|blurred-background)$",
        description="Центр или По лицу: крупное видео занимает 2/3 высоты поверх размытого фона. blurred-background — совместимый псевдоним центра.",
    )
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
    held_frames: int = 0
    largest_face_frames: int = 0
    average_confidence: float = 0.0


class RenderResponse(BaseModel):
    candidate_id: int
    export_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None
    warnings: list[str] = Field(default_factory=list)


class PreviewRenderResponse(BaseModel):
    candidate_id: int
    output_path: str
    subtitle_path: str | None
    cover_path: str | None
    duration_seconds: float
    preview_url: str


class RenderJobResponse(BaseModel):
    job: JobRead


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
    version: int = 1
    render_fingerprint: str | None = None


class AutoExportRequest(BaseModel):
    threshold: int | None = Field(default=None, ge=0, le=100)
    max_clips: int | None = Field(default=None, ge=1, le=20)
    use_nvenc: bool | None = None


class AutoExportResponse(BaseModel):
    approved: int
    rendered: int
    skipped: int
    export_paths: list[str]


__all__ = [
    "CandidateRead",
    "CandidateSnapshotRead",
    "BatchReviewRequest",
    "BatchRenderRequest",
    "BatchOutcomeRead",
    "KeyframeInfoRead",
    "KeyframeStripRead",
    "ReviewRequest",
    "CandidateEditRequest",
    "CandidateEditResponse",
    "ReviewResponse",
    "RenderRequest",
    "CandidateSubtitlePayload",
    "CandidateSubtitlesUpdate",
    "SubtitleQualityRead",
    "AutoCropResponse",
    "RenderResponse",
    "PreviewRenderResponse",
    "RenderJobResponse",
    "CandidateQualityRead",
    "ExportRead",
    "AutoExportRequest",
    "AutoExportResponse",
]
