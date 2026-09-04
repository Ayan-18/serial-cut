from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    episode_id: int | None
    kind: str
    status: str
    current_stage: str | None
    progress: float
    progress_message: str | None = None
    error_message: str | None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QueueSnapshotRead(BaseModel):
    queued: int
    running: int
    failed: int
    paused: bool
    eta_seconds: float | None = None


class QueueDataRead(BaseModel):
    snapshot: QueueSnapshotRead
    items: list[JobRead]


class LocalApiTokenRead(BaseModel):
    token: str


class QueueHealthRead(BaseModel):
    state: str
    queued: int
    running: int
    failed: int


class HealthRead(BaseModel):
    ok: bool
    service: str
    version: str
    commit: str | None = None
    boot_id: str
    token_fingerprint: str
    started_at: str
    uptime_seconds: float
    db_revision: str | None = None
    queue: QueueHealthRead


class VersionRead(BaseModel):
    service: str
    version: str
    commit: str | None = None
    boot_id: str
    started_at: str


class LogEntryRead(BaseModel):
    timestamp: str | None = None
    level: str
    logger: str
    message: str


class LogTailRead(BaseModel):
    path: str
    exists: bool
    size_bytes: int
    returned: int
    entries: list[LogEntryRead]


class JobStageRetryRequest(BaseModel):
    stage_name: str = Field(pattern="^(stage2_media|stage3_candidates|auto_export|render_clip|render_story_arc)$")


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


class QueueRunResponse(BaseModel):
    ran: bool
    job_id: int | None
    status: str
    message: str


class QueueStateResponse(BaseModel):
    state: str


__all__ = [
    "JobRead",
    "QueueSnapshotRead",
    "QueueDataRead",
    "LocalApiTokenRead",
    "QueueHealthRead",
    "HealthRead",
    "VersionRead",
    "LogEntryRead",
    "LogTailRead",
    "JobStageRetryRequest",
    "JobStageRead",
    "QueueRunResponse",
    "QueueStateResponse",
]
