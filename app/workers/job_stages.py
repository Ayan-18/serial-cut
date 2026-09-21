"""Job/stage lifecycle bookkeeping, split out of runner.py: recording a
stage or job as completed/failed/paused, the resume-from-stage bookkeeping,
progress-message formatting, and ETA estimation. None of this calls
`render_candidate`/`render_story_arc` — it only ever runs the callable a
caller in runner.py hands it — so it was safe to move out of that module."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import JobStatus
from app.infrastructure.processes import ProcessCancelledError
from app.models.entities import Job, JobStage
from app.workers.worker_identity import WORKER_ID

logger = logging.getLogger(__name__)

ANALYZE_STAGES = ["stage2_media", "stage3_candidates", "auto_export"]


class CancelledError(RuntimeError):
    pass


def _should_run_analyze_stage(stage: str, resume_stage: str) -> bool:
    return ANALYZE_STAGES.index(stage) >= ANALYZE_STAGES.index(resume_stage)


def _resume_progress(stage: str) -> float:
    return {
        "stage3_candidates": 0.45,
        "auto_export": 0.75,
        "render_story_arc": 0.0,
    }.get(stage, 0.0)


def _run_stage(session: Session, job: Job, name: str, fn: Callable[[], object], progress: float) -> None:
    job_id = job.id
    stage = _get_or_create_stage(session, job, name)
    stage.status = JobStatus.RUNNING.value
    stage.started_at = datetime.now(timezone.utc).isoformat()
    job.current_stage = name
    job.progress_message = _stage_start_message(name)
    session.commit()
    logger.info("Stage started: job_id=%s stage=%s", job_id, name)
    try:
        result = fn()
    except ProcessCancelledError as exc:
        _record_stage_terminal(session, job_id, name, JobStatus.PAUSED.value, str(exc))
        logger.info("Stage paused after cancellation: job_id=%s stage=%s error=%s", job_id, name, exc)
        raise CancelledError(str(exc)) from exc
    except Exception as exc:
        _record_stage_terminal(session, job_id, name, JobStatus.FAILED.value, str(exc))
        logger.exception("Stage failed: job_id=%s stage=%s", job_id, name)
        raise
    else:
        stage.status = JobStatus.COMPLETED.value
        stage.finished_at = datetime.now(timezone.utc).isoformat()
        job.progress = progress
        message = _stage_complete_message(name)
        stage_warnings = [str(item) for item in (getattr(result, "warnings", None) or [])]
        if stage_warnings:
            joined = "; ".join(stage_warnings)
            # Keep the stage COMPLETED, but surface the note in the job timeline
            # and the queue line.
            stage.error_message = f"⚠ {joined}"
            message = f"{message} · внимание: {joined}"
        else:
            stage.error_message = None
        job.progress_message = message
        session.commit()
        logger.info(
            "Stage completed: job_id=%s stage=%s warnings=%s", job_id, name, bool(stage_warnings)
        )


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


def _record_stage_terminal(
    session: Session,
    job_id: int,
    stage_name: str,
    status: str,
    error_message: str,
) -> None:
    bind = session.get_bind()
    session.rollback()
    factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
    with factory() as terminal_session:
        stage = terminal_session.scalar(
            select(JobStage).where(JobStage.job_id == job_id, JobStage.name == stage_name)
        )
        current = terminal_session.get(Job, job_id)
        if current is None or current.worker_id != WORKER_ID:
            return
        if stage is not None:
            stage.status = status
            stage.finished_at = datetime.now(timezone.utc).isoformat()
            stage.error_message = error_message
        current.progress_message = (
            error_message if status == JobStatus.PAUSED.value else f"Ошибка: {error_message}"
        )
        terminal_session.commit()
    session.expire_all()


def _record_job_terminal(
    session: Session,
    job_id: int,
    status: str,
    error_message: str | None,
    progress_message: str,
    *,
    progress: float | None = None,
    current_stage: str | None = None,
) -> bool:
    bind = session.get_bind()
    session.rollback()
    factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
    with factory() as terminal_session:
        current = terminal_session.get(Job, job_id)
        if current is None or current.worker_id != WORKER_ID:
            return False
        current.status = status
        current.error_message = error_message
        current.progress_message = progress_message
        current.finished_at = datetime.now(timezone.utc)
        current.cancel_requested = False
        if progress is not None:
            current.progress = progress
        if current_stage is not None:
            current.current_stage = current_stage
        _clear_job_lease(current)
        terminal_session.commit()
    session.expire_all()
    return True


def _clear_job_lease(job: Job) -> None:
    job.worker_id = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _update_render_progress(session: Session, job: Job, current: int, total: int) -> None:
    if total <= 0:
        return
    job.progress = min(0.94, max(0.02, 0.02 + 0.92 * current / total))
    job.progress_message = f"Рендер StoryArc: шаг {current} из {total}"
    session.commit()


def _update_analysis_progress(
    session: Session,
    job: Job,
    start: float,
    end: float,
    fraction: float,
    message: str,
) -> None:
    job.progress = max(start, min(end, start + (end - start) * max(0.0, min(1.0, fraction))))
    job.progress_message = message
    session.commit()


def _stage_start_message(name: str) -> str:
    return {
        "stage2_media": "Подготовка медиа",
        "stage3_candidates": "Анализ сюжета и кандидатов",
        "auto_export": "Автоматический экспорт",
        "render_clip": "Рендер клипа",
        "render_story_arc": "Рендер StoryArc",
    }.get(name, name)


def _stage_complete_message(name: str) -> str:
    return f"Этап завершён: {_stage_start_message(name)}"


def estimate_eta_seconds(session: Session) -> float | None:
    completed = session.scalars(select(Job).where(Job.status == JobStatus.COMPLETED.value)).all()
    durations_by_kind: dict[str, list[float]] = {}
    for job in completed:
        duration = _job_duration_seconds(job)
        if duration is not None and duration > 0:
            durations_by_kind.setdefault(job.kind, []).append(duration)
    durations = [value for values in durations_by_kind.values() for value in values]
    if not durations:
        return None
    fallback = sum(durations) / len(durations)
    pending = session.scalars(
        select(Job).where(Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]))
    ).all()
    eta = 0.0
    for job in pending:
        samples = durations_by_kind.get(job.kind) or []
        expected = sum(samples) / len(samples) if samples else fallback
        remaining = 1.0 - min(1.0, max(0.0, job.progress)) if job.status == JobStatus.RUNNING.value else 1.0
        eta += expected * remaining
    return eta


def _job_duration_seconds(job: Job) -> float | None:
    if job.started_at is None or job.finished_at is None:
        return None
    started = _aware(job.started_at)
    finished = _aware(job.finished_at)
    return (finished - started).total_seconds() if finished > started else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
