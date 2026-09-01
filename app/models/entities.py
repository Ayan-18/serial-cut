from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import EpisodeStage, JobKind, JobStatus, TrackKind
from app.models.base import Base, TimestampMixin


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    story_context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    episodes: Mapped[list["Episode"]] = relationship(back_populates="season", cascade="all, delete-orphan")
    characters: Mapped[list["Character"]] = relationship(back_populates="season", cascade="all, delete-orphan")
    story_arcs: Mapped[list["StoryArc"]] = relationship(back_populates="season", cascade="all, delete-orphan")
    video_scripts: Mapped[list["VideoScript"]] = relationship(back_populates="season", cascade="all, delete-orphan")


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_episodes_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default=EpisodeStage.DISCOVERED.value, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    probe_json: Mapped[dict | None] = mapped_column(JSON)
    proxy_path: Mapped[str | None] = mapped_column(Text)
    audio_path: Mapped[str | None] = mapped_column(Text)
    selected_audio_stream_index: Mapped[int | None] = mapped_column(Integer)
    selected_subtitle_stream_index: Mapped[int | None] = mapped_column(Integer)
    story_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    required_events_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    excluded_events_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    spoilers_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    candidate_mode: Mapped[str] = mapped_column(String(32), default="highlights", nullable=False)

    season: Mapped[Season] = relationship(back_populates="episodes")
    tracks: Mapped[list["MediaTrack"]] = relationship(back_populates="episode", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="episode")


class MediaTrack(TimestampMixin, Base):
    __tablename__ = "media_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    stream_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=TrackKind.OTHER.value, nullable=False)
    codec: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict | None] = mapped_column(JSON)

    episode: Mapped[Episode] = relationship(back_populates="tracks")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64), default=JobKind.ANALYZE_EPISODE.value, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default=JobStatus.QUEUED.value, nullable=False, index=True)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    stage_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    progress_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(160), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    episode: Mapped[Episode | None] = relationship(back_populates="jobs")
    stages: Mapped[list["JobStage"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobStage(TimestampMixin, Base):
    __tablename__ = "job_stages"
    __table_args__ = (UniqueConstraint("job_id", "name", name="uq_job_stage_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), default=JobStatus.QUEUED.value, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="stages")


class TranscriptSegment(TimestampMixin, Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_label: Mapped[str | None] = mapped_column(String(64))


class WordTimestamp(TimestampMixin, Base):
    __tablename__ = "word_timestamps"

    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("transcript_segments.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    word: Mapped[str] = mapped_column(String(255), nullable=False)


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class EpisodeOutline(TimestampMixin, Base):
    __tablename__ = "episode_outlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, unique=True)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class ClipCandidate(TimestampMixin, Base):
    __tablename__ = "clip_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    moment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    scores_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    problems_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    crop_mode: Mapped[str] = mapped_column(String(64), default="blurred-background", nullable=False)
    crop_offset_x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    crop_scale: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    crop_keyframes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)
    story_order: Mapped[int | None] = mapped_column(Integer)
    story_role: Mapped[str | None] = mapped_column(String(64))
    continuity_note: Mapped[str | None] = mapped_column(Text)
    edit_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StoryArc(TimestampMixin, Base):
    __tablename__ = "story_arcs"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    arc_type: Mapped[str] = mapped_column(String(64), default="custom", nullable=False)
    output_format: Mapped[str] = mapped_column(String(64), default="shorts_series", nullable=False)
    target_character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    total_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    edit_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    season: Mapped[Season] = relationship(back_populates="story_arcs")
    target_character: Mapped["Character | None"] = relationship()
    segments: Mapped[list["StoryArcSegment"]] = relationship(
        back_populates="story_arc",
        cascade="all, delete-orphan",
        order_by="StoryArcSegment.sort_order",
    )
    exports: Mapped[list["StoryArcExport"]] = relationship(back_populates="story_arc", cascade="all, delete-orphan")
    video_scripts: Mapped[list["VideoScript"]] = relationship(back_populates="story_arc", cascade="all, delete-orphan")
    publishing_plans: Mapped[list["PublishingPlan"]] = relationship(back_populates="story_arc", cascade="all, delete-orphan")


class StoryArcSegment(TimestampMixin, Base):
    __tablename__ = "story_arc_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_arc_id: Mapped[int] = mapped_column(ForeignKey("story_arcs.id"), nullable=False, index=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("clip_candidates.id"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    role: Mapped[str | None] = mapped_column(String(64))
    candidate_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manually_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    story_arc: Mapped[StoryArc] = relationship(back_populates="segments")
    episode: Mapped[Episode] = relationship()
    candidate: Mapped[ClipCandidate | None] = relationship()


class StoryArcExport(TimestampMixin, Base):
    __tablename__ = "story_arc_exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_arc_id: Mapped[int] = mapped_column(ForeignKey("story_arcs.id"), nullable=False, index=True)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_path: Mapped[str | None] = mapped_column(Text)
    cover_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, default=1080, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1920, nullable=False)
    include_subtitles: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    preset_name: Mapped[str] = mapped_column(String(64), default="youtube_shorts", nullable=False)
    segment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False, index=True)
    arc_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transition_style: Mapped[str] = mapped_column(String(32), default="cut", nullable=False)
    narration_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    render_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)

    story_arc: Mapped[StoryArc] = relationship(back_populates="exports")


class VideoScript(TimestampMixin, Base):
    __tablename__ = "video_scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    story_arc_id: Mapped[int | None] = mapped_column(ForeignKey("story_arcs.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    style: Mapped[str] = mapped_column(String(64), default="chronological", nullable=False)
    script_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    structure_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)

    season: Mapped[Season] = relationship(back_populates="video_scripts")
    story_arc: Mapped[StoryArc | None] = relationship(back_populates="video_scripts")


class PublishingPlan(TimestampMixin, Base):
    __tablename__ = "publishing_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    story_arc_id: Mapped[int | None] = mapped_column(ForeignKey("story_arcs.id"), index=True)
    story_arc_export_id: Mapped[int | None] = mapped_column(ForeignKey("story_arc_exports.id"), index=True)
    platform: Mapped[str] = mapped_column(String(64), default="youtube_shorts", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hashtags_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)

    season: Mapped[Season] = relationship()
    story_arc: Mapped[StoryArc | None] = relationship(back_populates="publishing_plans")
    story_arc_export: Mapped[StoryArcExport | None] = relationship()


class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("season_id", "name", name="uq_character_season_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    aliases_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    photos_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    voice_profile_json: Mapped[dict | None] = mapped_column(JSON)
    color: Mapped[str] = mapped_column(String(16), default="#b9ddff", nullable=False)

    season: Mapped[Season] = relationship(back_populates="characters")


class SpeakerIdentity(TimestampMixin, Base):
    __tablename__ = "speaker_identities"
    __table_args__ = (UniqueConstraint("episode_id", "source_label", name="uq_speaker_identity_episode_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False, index=True)
    source_label: Mapped[str] = mapped_column(String(64), nullable=False)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)


class CandidateSubtitle(TimestampMixin, Base):
    __tablename__ = "candidate_subtitles"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("clip_candidates.id"), nullable=False, index=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_label: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ReviewDecision(TimestampMixin, Base):
    __tablename__ = "review_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("clip_candidates.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    adjusted_start_time: Mapped[float | None] = mapped_column(Float)
    adjusted_end_time: Mapped[float | None] = mapped_column(Float)
    crop_mode: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)


class RenderPreset(TimestampMixin, Base):
    __tablename__ = "render_presets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    settings_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class Export(TimestampMixin, Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("clip_candidates.id"), nullable=False, index=True)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_path: Mapped[str | None] = mapped_column(Text)
    subtitle_path: Mapped[str | None] = mapped_column(Text)
    cover_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, default=1080, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1920, nullable=False)
    include_subtitles: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    preset_name: Mapped[str] = mapped_column(String(64), default="youtube_shorts", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False, index=True)
    candidate_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    render_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
