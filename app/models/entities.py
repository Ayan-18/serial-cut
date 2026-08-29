from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import EpisodeStage, JobKind, JobStatus, TrackKind
from app.models.base import Base, TimestampMixin


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    episodes: Mapped[list["Episode"]] = relationship(back_populates="season", cascade="all, delete-orphan")


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
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)

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
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False, index=True)


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


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
