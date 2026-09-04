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


class ImportFileErrorRead(BaseModel):
    file_name: str
    reason: str


class ImportResponse(BaseModel):
    season_id: int
    created: int
    skipped_duplicates: int
    episode_ids: list[int]
    scanned: int = 0
    errors: list[ImportFileErrorRead] = Field(default_factory=list)


class EpisodeOutlineRead(BaseModel):
    episode_id: int
    summary_json: dict


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


class Stage2RunResponse(BaseModel):
    episode_id: int
    stage: str
    audio_path: str | None
    proxy_path: str | None
    transcript_segments: int
    scenes: int
    warnings: list[str] = Field(default_factory=list)


class Stage3RunResponse(BaseModel):
    episode_id: int
    stage: str
    outline_created: bool
    candidates: int


class EnqueueSeasonRequest(BaseModel):
    auto: bool = False


class EnqueueEpisodeRequest(BaseModel):
    resume_from_stage: str | None = Field(default=None, pattern="^(stage2_media|stage3_candidates|auto_export)$")
    auto: bool | None = None
    threshold: int | None = Field(default=None, ge=0, le=100)
    max_clips: int | None = Field(default=None, ge=1, le=20)
    use_nvenc: bool | None = None


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
    media_warnings: list[str] = Field(default_factory=list)


__all__ = [
    "SeasonImportRequest",
    "EpisodeRead",
    "SeasonRead",
    "ImportFileErrorRead",
    "ImportResponse",
    "EpisodeOutlineRead",
    "StoryContextRead",
    "StoryContextUpdate",
    "Stage2RunResponse",
    "Stage3RunResponse",
    "EnqueueSeasonRequest",
    "EnqueueEpisodeRequest",
    "EpisodeQualityRead",
]
