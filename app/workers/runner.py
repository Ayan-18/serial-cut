from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Callable
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.auto import auto_approve_and_export
from app.application.queue_control import get_queue_state
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.stage2 import run_stage2_media_analysis
from app.application.stage3 import run_stage3_candidate_analysis
from app.application.stage4 import render_candidate
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.models.entities import Job, JobStage
from app.workers.queue import next_queued_job


Stage2Func = Callable[[Session, int, Settings], object]
Stage3Func = Callable[[Session, int, Settings], object]


_RUNNER_LOCK = Lock()


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
    if not _RUNNER_LOCK.acquire(blocking=False):
        return WorkerRunResult(False, None, "busy", "Обработчик уже выполняет другую задачу")
    try:
        try:
            with processing_guard():
                return _run_next_job_unlocked(session, settings, stage2_func, stage3_func)
        except ProcessingBusyError as exc:
            return WorkerRunResult(False, None, "busy", str(exc))
    finally:
        _RUNNER_LOCK.release()


def _run_next_job_unlocked(
    session: Session,
    settings: Settings,
    stage2_func: Stage2Func,
    stage3_func: Stage3Func,
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
    session.commit()
    started = monotonic()
    try:
        payload = job.payload or {}
        if job.kind == JobKind.RENDER_CLIP.value:
            candidate_id = int(payload["candidate_id"])
            _run_stage(
                session,
                job,
                "render_clip",
                lambda: render_candidate(
                    session,
                    candidate_id,
                    settings,
                    include_subtitles=bool(payload.get("include_subtitles", True)),
                    use_nvenc=payload.get("use_nvenc"),
                    preset_name=payload.get("preset_name"),
                    loudnorm_two_pass=payload.get("loudnorm_two_pass"),
                    force_rerender=bool(payload.get("force_rerender", False)),
                ),
                0.95,
            )
        else:
            _run_stage(session, job, "stage2_media", lambda: stage2_func(session, job.episode_id, settings), 0.45)
            _raise_if_cancelled(session, job)
            _run_stage(session, job, "stage3_candidates", lambda: stage3_func(session, job.episode_id, settings), 0.75)
            _raise_if_cancelled(session, job)
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
        session.commit()
        elapsed = monotonic() - started
        return WorkerRunResult(True, job.id, job.status, f"Задача завершена за {elapsed:.1f} сек")
    except CancelledError as exc:
        job.status = JobStatus.PAUSED.value
        job.error_message = str(exc)
        session.commit()
        return WorkerRunResult(True, job.id, job.status, str(exc))
    except Exception as exc:
        job.status = JobStatus.FAILED.value
        job.error_message = str(exc)
        session.commit()
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
    session.commit()
    fn()
    stage.status = JobStatus.COMPLETED.value
    stage.finished_at = datetime.now(timezone.utc).isoformat()
    stage.error_message = None
    job.progress = progress
    session.commit()


def _get_or_create_stage(session: Session, job: Job, name: str) -> JobStage:
    stage = session.scalar(select(JobStage).where(JobStage.job_id == job.id).where(JobStage.name == name))
    if stage is None:
        stage = JobStage(job_id=job.id, name=name)
        session.add(stage)
        session.flush()
    return stage


def _raise_if_cancelled(session: Session, job: Job) -> None:
    session.refresh(job)
    if job.cancel_requested or job.status == JobStatus.CANCEL_REQUESTED.value:
        raise CancelledError("Задача остановлена по запросу пользователя")

