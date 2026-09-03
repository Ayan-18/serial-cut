from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.orm import Session

from app.domain.enums import EpisodeStage, JobKind, JobStatus
from app.models.entities import ClipCandidate, Episode, Job, JobStage, Season, StoryArc


PIPELINE_STAGES = [
    EpisodeStage.DISCOVERED.value,
    EpisodeStage.PROBED.value,
    EpisodeStage.PROXIED.value,
    EpisodeStage.TRANSCRIBED.value,
    EpisodeStage.SCENES_DETECTED.value,
    EpisodeStage.OUTLINED.value,
    EpisodeStage.CANDIDATES_GENERATED.value,
    EpisodeStage.CANDIDATES_VALIDATED.value,
    EpisodeStage.AWAITING_REVIEW.value,
    EpisodeStage.RENDERED.value,
]

JOB_STAGE_ORDER = {
    JobKind.ANALYZE_EPISODE.value: ["stage2_media", "stage3_candidates", "auto_export"],
    JobKind.RENDER_CLIP.value: ["render_clip"],
    JobKind.RENDER_STORY_ARC.value: ["render_story_arc"],
}


@dataclass(frozen=True)
class QueueSnapshot:
    queued: int
    running: int
    failed: int
    paused: bool = False
    eta_seconds: float | None = None


def enqueue_episode_analysis(session: Session, episode_id: int, payload: dict | None = None) -> Job:
    payload = dict(payload or {})
    existing = session.scalar(
        select(Job).where(
            Job.episode_id == episode_id,
            Job.kind == JobKind.ANALYZE_EPISODE.value,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.PAUSED.value]),
        )
    )
    if existing is not None:
        if payload and existing.status != JobStatus.RUNNING.value:
            existing_payload = dict(existing.payload or {})
            existing_payload.update(payload)
            existing.payload = existing_payload
            resume_from_stage = payload.get("resume_from_stage")
            if resume_from_stage:
                existing.current_stage = str(resume_from_stage)
                existing.progress = _job_stage_progress(str(resume_from_stage))
        return existing
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"Episode {episode_id} not found")
    job = Job(
        episode_id=episode_id,
        kind=JobKind.ANALYZE_EPISODE.value,
        status=JobStatus.QUEUED.value,
        current_stage=str(payload.get("resume_from_stage") or episode.stage),
        stage_index=_stage_index(episode.stage),
        progress=_job_stage_progress(str(payload.get("resume_from_stage") or "")),
        payload=payload or None,
    )
    session.add(job)
    session.flush()
    return job


def enqueue_season_analysis(session: Session, season_id: int, auto: bool = False) -> list[Job]:
    season = session.get(Season, season_id)
    if season is None:
        raise ValueError(f"Season {season_id} not found")
    episodes = session.scalars(select(Episode).where(Episode.season_id == season_id).order_by(Episode.file_name)).all()
    jobs: list[Job] = []
    for episode in episodes:
        job = enqueue_episode_analysis(session, episode.id)
        payload = dict(job.payload or {})
        payload["auto"] = auto
        job.payload = payload
        jobs.append(job)
    return jobs


def enqueue_candidate_render(session: Session, candidate_id: int, payload: dict) -> Job:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    existing_jobs = session.scalars(
        select(Job).where(
            Job.kind == JobKind.RENDER_CLIP.value,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.PAUSED.value]),
        )
    ).all()
    for existing in existing_jobs:
        if (existing.payload or {}).get("candidate_id") == candidate_id:
            return existing
    job = Job(
        episode_id=candidate.episode_id,
        kind=JobKind.RENDER_CLIP.value,
        status=JobStatus.QUEUED.value,
        current_stage="render_clip",
        payload={"candidate_id": candidate_id, **payload},
    )
    session.add(job)
    session.flush()
    return job


def enqueue_story_arc_render(session: Session, story_arc_id: int, payload: dict) -> Job:
    arc = session.get(StoryArc, story_arc_id)
    if arc is None:
        raise ValueError(f"StoryArc {story_arc_id} not found")
    existing_jobs = session.scalars(
        select(Job).where(
            Job.kind == JobKind.RENDER_STORY_ARC.value,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.PAUSED.value]),
        )
    ).all()
    for existing in existing_jobs:
        if (existing.payload or {}).get("story_arc_id") == story_arc_id:
            return existing
    job = Job(
        episode_id=arc.segments[0].episode_id if arc.segments else None,
        kind=JobKind.RENDER_STORY_ARC.value,
        status=JobStatus.QUEUED.value,
        current_stage="render_story_arc",
        payload={"story_arc_id": story_arc_id, **payload},
    )
    session.add(job)
    session.flush()
    return job


def recover_interrupted_jobs(session: Session) -> int:
    now = datetime.now(timezone.utc)
    jobs = session.scalars(
        select(Job).where(
            Job.status.in_([JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value]),
            or_(Job.lease_expires_at.is_(None), Job.lease_expires_at <= now),
        )
    ).all()
    for job in jobs:
        if job.status == JobStatus.CANCEL_REQUESTED.value:
            job.status = JobStatus.PAUSED.value
            job.error_message = "Остановка завершена при перезапуске приложения"
            job.progress_message = "Задача остановлена"
            job.finished_at = datetime.now(timezone.utc)
        else:
            job.status = JobStatus.QUEUED.value
            job.error_message = "Задача восстановлена после перезапуска приложения"
            job.progress_message = "Ожидает повторного запуска после восстановления"
            job.started_at = None
            job.finished_at = None
        job.worker_id = None
        job.lease_expires_at = None
        job.heartbeat_at = None
    return len(jobs)


def request_cancel(session: Session, job_id: int) -> Job:
    job = _get_job(session, job_id)
    if job.status in {JobStatus.COMPLETED.value, JobStatus.FAILED.value}:
        return job
    if job.status == JobStatus.QUEUED.value:
        job.cancel_requested = False
        job.status = JobStatus.PAUSED.value
        job.progress_message = "Задача остановлена до запуска"
        job.finished_at = datetime.now(timezone.utc)
    elif job.status != JobStatus.PAUSED.value:
        job.cancel_requested = True
        job.status = JobStatus.CANCEL_REQUESTED.value
        job.progress_message = "Остановка запрошена"
    return job


def retry_job(session: Session, job_id: int) -> Job:
    job = _get_job(session, job_id)
    payload = dict(job.payload or {})
    payload.pop("resume_from_stage", None)
    job.payload = payload or None
    job.status = JobStatus.QUEUED.value
    job.cancel_requested = False
    job.error_message = None
    job.progress_message = "Ожидает повторного запуска"
    job.started_at = None
    job.finished_at = None
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.attempts += 1
    return job


def retry_job_from_stage(session: Session, job_id: int, stage_name: str) -> Job:
    job = _get_job(session, job_id)
    stages = JOB_STAGE_ORDER.get(job.kind)
    if stages is None or stage_name not in stages:
        raise ValueError(f"Stage {stage_name} cannot be retried for job kind {job.kind}")
    payload = dict(job.payload or {})
    payload["resume_from_stage"] = stage_name
    job.payload = payload
    job.current_stage = stage_name
    job.progress = _job_stage_progress(stage_name)
    job.status = JobStatus.QUEUED.value
    job.cancel_requested = False
    job.error_message = None
    job.progress_message = "Ожидает повторного запуска выбранного этапа"
    job.started_at = None
    job.finished_at = None
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.attempts += 1
    start_index = stages.index(stage_name)
    rows = session.scalars(select(JobStage).where(JobStage.job_id == job.id)).all()
    for stage in rows:
        if stage.name in stages and stages.index(stage.name) >= start_index:
            stage.status = JobStatus.QUEUED.value
            stage.started_at = None
            stage.finished_at = None
            stage.error_message = None
    return job


class JobBusyError(RuntimeError):
    """Raised when a job cannot be removed because it is still executing."""


def delete_job(session: Session, job_id: int) -> None:
    job = _get_job(session, job_id)
    if job.status in {JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value}:
        raise JobBusyError(
            f"Задача №{job_id} выполняется. Сначала остановите её, затем удалите."
        )
    session.execute(delete(JobStage).where(JobStage.job_id == job_id))
    session.delete(job)


def queue_snapshot(session: Session) -> QueueSnapshot:
    jobs = session.scalars(select(Job)).all()
    return QueueSnapshot(
        queued=sum(job.status == JobStatus.QUEUED.value for job in jobs),
        running=sum(job.status == JobStatus.RUNNING.value for job in jobs),
        failed=sum(job.status == JobStatus.FAILED.value for job in jobs),
    )


def claim_next_queued_job(
    session: Session,
    worker_id: str,
    *,
    lease_seconds: int = 120,
) -> Job | None:
    """Atomically claim one job and one global heavy-processing lease."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=max(30, lease_seconds))
    candidate_id = (
        select(Job.id)
        .where(Job.status == JobStatus.QUEUED.value)
        .order_by(Job.created_at, Job.id)
        .limit(1)
        .scalar_subquery()
    )
    active_lease = exists(
        select(Job.id).where(
            Job.status.in_([JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value]),
            Job.lease_expires_at > now,
        )
    ).correlate(None)
    claimed_id = session.execute(
        update(Job)
        .where(
            Job.id == candidate_id,
            Job.status == JobStatus.QUEUED.value,
            ~active_lease,
        )
        .values(
            status=JobStatus.RUNNING.value,
            worker_id=worker_id,
            heartbeat_at=now,
            lease_expires_at=expires,
            error_message=None,
            progress_message="Запуск задачи",
            started_at=now,
            finished_at=None,
        )
        .returning(Job.id)
    ).scalar_one_or_none()
    session.commit()
    if claimed_id is None:
        return None
    session.expire_all()
    return session.get(Job, claimed_id)


def heartbeat_job_lease(
    session: Session,
    job_id: int,
    worker_id: str,
    *,
    lease_seconds: int = 120,
) -> bool:
    now = datetime.now(timezone.utc)
    result = session.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.worker_id == worker_id,
            Job.status.in_([JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value]),
        )
        .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=max(30, lease_seconds)))
    )
    session.commit()
    return bool(result.rowcount)


def _get_job(session: Session, job_id: int) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    return job


def _stage_index(stage: str | None) -> int:
    if stage in PIPELINE_STAGES:
        return PIPELINE_STAGES.index(stage)
    return 0


def _job_stage_progress(stage: str) -> float:
    return {
        "stage2_media": 0.0,
        "stage3_candidates": 0.45,
        "auto_export": 0.75,
        "render_clip": 0.0,
        "render_story_arc": 0.0,
    }.get(stage, 0.0)
