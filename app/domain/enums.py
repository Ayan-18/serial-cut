from __future__ import annotations

from enum import Enum


class EpisodeStage(str, Enum):
    DISCOVERED = "discovered"
    PROBED = "probed"
    PROXIED = "proxied"
    TRANSCRIBED = "transcribed"
    SCENES_DETECTED = "scenes_detected"
    OUTLINED = "outlined"
    CANDIDATES_GENERATED = "candidates_generated"
    CANDIDATES_VALIDATED = "candidates_validated"
    AWAITING_REVIEW = "awaiting_review"
    AUTO_APPROVED = "auto_approved"
    RENDERED = "rendered"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    FAILED = "failed"
    COMPLETED = "completed"


class JobKind(str, Enum):
    ANALYZE_EPISODE = "analyze_episode"
    PROBE_EPISODE = "probe_episode"
    RENDER_CLIP = "render_clip"
    RENDER_STORY_ARC = "render_story_arc"


class TrackKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    OTHER = "other"
