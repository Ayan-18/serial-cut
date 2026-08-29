from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.auto import auto_approve_and_export
from app.application.queue_control import get_queue_state
from app.application.stage2 import run_stage2_media_analysis
from app.application.stage3 import run_stage3_candidate_analysis
from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import Job, JobStage
from app.workers.queue import next_queued_job


Stage2Func = Callable[[Session, int, Settings], object]
Stage3Func = Callable[[Session, int, Settings], object]


@dataclass(frozen=True)
class WorkerRunResult:
    ran: bool
    job_id: int | None
    status: str
    message: str


def run_next_job(
    session: Session,
    settings: Settings,
    stage2_func: Stage2Func = run_stage2_media_analysis,
    stage3_func: Stage3Func = run_stage3_candidate_analysis,
) -> WorkerRunResult:
    if get_queue_state(session) == "paused":
        return WorkerRunResult(False, None, "paused", "Очередь на паузе")
    job = next_queued_job(session)
    if job is None:
        return WorkerRunResult(False, None, "idle", "Нет задач в очереди")
    if job.episode_id is None:
        job.status = JobStatus.FAILED.value
        job.error_message = "У job нет episode_id"
        return WorkerRunResult(True, job.id, job.status, job.error_message)

    job.status = JobStatus.RUNNING.value
    job.error_message = None
    job.progress = 0.0
    session.flush()
    started = monotonic()
    try:
        _run_stage(session, job, "stage2_media", lambda: stage2_func(session, job.episode_id, settings), 0.45)
        _raise_if_cancelled(job)
        _run_stage(session, job, "stage3_candidates", lambda: stage3_func(session, job.episode_id, settings), 0.75)
        _raise_if_cancelled(job)
        payload = job.payload or {}
        auto_enabled = bool(payload.get("auto", settings.auto_mode_enabled))
        if auto_enabled:
            _run_stage(
                session,
                job,
                "auto_export",
                lambda: auto_approve_and_export(
                    session,
                    job.episode_id,
                    settings,
                    threshold=int(payload.get("threshold", settings.auto_score_threshold)),
                    max_clips=int(payload.get("max_clips", settings.max_clips_per_episode)),
                    use_nvenc=bool(payload.get("use_nvenc", settings.render_use_nvenc)),
                ),
                0.95,
            )
        job.status = JobStatus.COMPLETED.value
        job.progress = 1.0
        job.current_stage = "completed"
        session.flush()
        elapsed = monotonic() - started
        return WorkerRunResult(True, job.id, job.status, f"Задача завершена за {elapsed:.1f} сек")
    except CancelledError as exc:
        job.status = JobStatus.PAUSED.value
        job.error_message = str(exc)
        session.flush()
        return WorkerRunResult(True, job.id, job.status, str(exc))
    except Exception as exc:
        job.status = JobStatus.FAILED.value
        job.error_message = str(exc)
        session.flush()
        return WorkerRunResult(True, job.id, job.status, str(exc))


def estimate_eta_seconds(session: Session) -> float | None:
    completed = session.scalars(select(Job).where(Job.status == JobStatus.COMPLETED.value)).all()
    durations = [
        (job.updated_at - job.created_at).total_seconds()
        for job in completed
        if job.updated_at is not None and job.created_at is not None and job.updated_at > job.created_at
    ]
    if not durations:
        return None
    queued = len(session.scalars(select(Job).where(Job.status == JobStatus.QUEUED.value)).all())
    if queued == 0:
        return 0.0
    return (sum(durations) / len(durations)) * queued


class CancelledError(RuntimeError):
    pass


def _run_stage(session: Session, job: Job, name: str, fn: Callable[[], object], progress: float) -> None:
    stage = _get_or_create_stage(session, job, name)
    stage.status = JobStatus.RUNNING.value
    stage.started_at = datetime.now(timezone.utc).isoformat()
    job.current_stage = name
    session.flush()
    fn()
    stage.status = JobStatus.COMPLETED.value
    stage.finished_at = datetime.now(timezone.utc).isoformat()
    stage.error_message = None
    job.progress = progress
    session.flush()


def _get_or_create_stage(session: Session, job: Job, name: str) -> JobStage:
    stage = session.scalar(select(JobStage).where(JobStage.job_id == job.id).where(JobStage.name == name))
    if stage is None:
        stage = JobStage(job_id=job.id, name=name)
        session.add(stage)
        session.flush()
    return stage


def _raise_if_cancelled(job: Job) -> None:
    if job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED.value:
        raise CancelledError("Задача остановлена по запросу пользователя")

