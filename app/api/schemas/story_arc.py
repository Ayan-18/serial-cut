from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.schemas.common import JobRead


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
    transition_style: str = "cut"
    narration_included: bool = False
    version: int = 1
    render_fingerprint: str | None = None


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
    include_narration: bool = True
    narration_mode: str = Field(default="first_person", pattern="^(none|narrator|first_person)$")


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
    mode: str = "first_person"
    source: str = "template"
    tts_notice: str = "Локальная TTS-озвучка не имитирует голос актёра или персонажа."


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


__all__ = [
    "StoryArcCreateRequest",
    "StoryArcSegmentRead",
    "StoryArcExportRead",
    "StoryArcRead",
    "StoryArcRenderRequest",
    "StoryArcRenderResponse",
    "StoryArcRenderJobResponse",
    "StoryArcUpdateRequest",
    "StoryArcSegmentUpdateRequest",
    "StoryArcCandidateAddRequest",
    "NarrationRead",
    "NarrationAudioRead",
    "VideoScriptCreateRequest",
    "VideoScriptUpdateRequest",
    "VideoScriptRead",
]
