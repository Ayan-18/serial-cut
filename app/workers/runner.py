from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
import socket
from time import monotonic
from typing import Callable
from threading import Event, Lock, Thread
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.application.auto import auto_approve_and_export
from app.application.queue_control import get_queue_state
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.stage4 import render_candidate
from app.application.story_arc_render import render_story_arc
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError, run_process_cancellable
from app.models.entities import Job, JobStage
from app.workers.queue import claim_next_queued_job, heartbeat_job_lease, recover_interrupted_jobs


logger = logging.getLogger(__name__)


Stage2Func = Callable[..., object]
Stage3Func = Callable[..., object]


_RUNNER_LOCK = Lock()
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}"


@dataclass(frozen=True)
class WorkerRunResult:
    ran: bool
    job_id: int | None
    status: str
    message: str


def run_next_job(
    session: Session,
    settings: Settings,
    stage2_func: Stage2Func | None = None,
    stage3_func: Stage3Func | None = None,
) -> WorkerRunResult:
    if not _RUNNER_LOCK.acquire(blocking=False):
        logger.info("Worker run skipped: another job is already running")
        return WorkerRunResult(False, None, "busy", "Обработчик уже выполняет другую задачу")
    try:
        try:
            with processing_guard():
                return _run_next_job_unlocked(session, settings, stage2_func, stage3_func)
        except ProcessingBusyError as exc:
            logger.info("Worker run skipped by processing guard: %s", exc)
            return WorkerRunResult(False, None, "busy", str(exc))
    finally:
        _RUNNER_LOCK.release()


def _run_next_job_unlocked(
    session: Session,
    settings: Settings,
    stage2_func: Stage2Func | None,
    stage3_func: Stage3Func | None,
) -> WorkerRunResult:
    if get_queue_state(session) == "paused":
        logger.info("Worker run skipped: queue is paused")
        return WorkerRunResult(False, None, "paused", "Очередь на паузе")
    recover_interrupted_jobs(session)
    session.commit()
    job = claim_next_queued_job(session, _WORKER_ID)
    if job is None:
        logger.debug("Worker run skipped: no queued jobs")
        return WorkerRunResult(False, None, "idle", "Нет задач в очереди")
    logger.info("Claimed job: id=%s kind=%s episode_id=%s", job.id, job.kind, job.episode_id)
    heartbeat = _LeaseHeartbeat(session.get_bind(), job.id, _WORKER_ID)
    heartbeat.start()
    if job.episode_id is None and job.kind != JobKind.RENDER_STORY_ARC.value:
        heartbeat.stop()
        message = "У job нет episode_id"
        _record_job_terminal(session, job.id, JobStatus.FAILED.value, message, "Ошибка запуска")
        return WorkerRunResult(True, job.id, JobStatus.FAILED.value, message)

    payload = job.payload or {}
    resume_from_stage = str(payload.get("resume_from_stage") or "")
    job.progress = _resume_progress(resume_from_stage)
    session.commit()
    started = monotonic()
    try:
        cancellable_runner = lambda args, timeout: run_process_cancellable(
            args,
            timeout,
            lambda: _job_cancel_requested(session.get_bind(), job.id),
        )
        if job.kind == JobKind.RENDER_CLIP.value:
            if resume_from_stage and resume_from_stage != "render_clip":
                raise ValueError(f"Этап {resume_from_stage} нельзя запустить для рендера")
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
                    runner=cancellable_runner,
                ),
                0.95,
            )
        elif job.kind == JobKind.RENDER_STORY_ARC.value:
            if resume_from_stage and resume_from_stage != "render_story_arc":
                raise ValueError(f"Этап {resume_from_stage} нельзя запустить для StoryArc рендера")
            story_arc_id = int(payload["story_arc_id"])
            _run_stage(
                session,
                job,
                "render_story_arc",
                lambda: render_story_arc(
                    session,
                    story_arc_id,
                    settings,
                    include_subtitles=bool(payload.get("include_subtitles", True)),
                    use_nvenc=payload.get("use_nvenc"),
                    preset_name=payload.get("preset_name"),
                    loudnorm_two_pass=payload.get("loudnorm_two_pass"),
                    force_rerender=bool(payload.get("force_rerender", False)),
                    transition_style=str(payload.get("transition_style") or "cut"),
                    include_narration=bool(payload.get("include_narration", True)),
                    narration_mode=str(payload.get("narration_mode") or "first_person"),
                    progress_callback=lambda current, total, _message: _update_render_progress(
                        session, job, current, total
                    ),
                    cancel_check=lambda: _job_cancel_requested(session.get_bind(), job.id),
                    runner=cancellable_runner,
                ),
                0.95,
            )
        else:
            default_stage2 = stage2_func is None
            default_stage3 = stage3_func is None
            if stage2_func is None or stage3_func is None:
                from app.application.stage2 import run_stage2_media_analysis
                from app.application.stage3 import run_stage3_candidate_analysis

                stage2_func = stage2_func or run_stage2_media_analysis
                stage3_func = stage3_func or run_stage3_candidate_analysis
            if resume_from_stage and resume_from_stage not in ANALYZE_STAGES:
                raise ValueError(f"Неизвестный этап анализа: {resume_from_stage}")
            resume_stage = resume_from_stage or "stage2_media"
            if _should_run_analyze_stage("stage2_media", resume_stage):
                _run_stage(
                    session,
                    job,
                    "stage2_media",
                    (
                        (
                            lambda: stage2_func(
                                session,
                                job.episode_id,
                                settings,
                                progress_callback=lambda value, message: _update_analysis_progress(
                                    session, job, 0.0, 0.45, value, message
                                ),
                                cancel_check=lambda: _job_cancel_requested(session.get_bind(), job.id),
                                runner=cancellable_runner,
                            )
                        )
                        if default_stage2
                        else (lambda: stage2_func(session, job.episode_id, settings))
                    ),
                    0.45,
                )
                _raise_if_cancelled(session, job)
            if _should_run_analyze_stage("stage3_candidates", resume_stage):
                _run_stage(
                    session,
                    job,
                    "stage3_candidates",
                    (
                        (
                            lambda: stage3_func(
                                session,
                                job.episode_id,
                                settings,
                                progress_callback=lambda value, message: _update_analysis_progress(
                                    session, job, 0.45, 0.75, value, message
                                ),
                                cancel_check=lambda: _job_cancel_requested(session.get_bind(), job.id),
                            )
                        )
                        if default_stage3
                        else (lambda: stage3_func(session, job.episode_id, settings))
                    ),
                    0.75,
                )
                _raise_if_cancelled(session, job)
            auto_enabled = bool(payload.get("auto", settings.auto_mode_enabled))
            if auto_enabled or resume_stage == "auto_export":
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
        heartbeat.stop()
        completed = _record_job_terminal(
            session,
            job.id,
            JobStatus.COMPLETED.value,
            None,
            "Задача завершена",
            progress=1.0,
            current_stage="completed",
        )
        elapsed = monotonic() - started
        if not completed:
            logger.warning("Worker lost job lease before completion: id=%s", job.id)
            return WorkerRunResult(False, job.id, "lost_lease", "Lease задачи уже перешёл другому worker")
        logger.info("Job completed: id=%s kind=%s elapsed=%.1fs", job.id, job.kind, elapsed)
        return WorkerRunResult(True, job.id, job.status, f"Задача завершена за {elapsed:.1f} сек")
    except CancelledError as exc:
        heartbeat.stop()
        _record_job_terminal(
            session,
            job.id,
            JobStatus.PAUSED.value,
            str(exc),
            "Задача остановлена",
        )
        logger.info("Job paused after cancellation: id=%s error=%s", job.id, exc)
        return WorkerRunResult(True, job.id, JobStatus.PAUSED.value, str(exc))
    except Exception as exc:
        heartbeat.stop()
        _record_job_terminal(
            session,
            job.id,
            JobStatus.FAILED.value,
            str(exc),
            "Ошибка выполнения",
        )
        logger.exception("Job failed: id=%s kind=%s", job.id, job.kind)
        return WorkerRunResult(True, job.id, JobStatus.FAILED.value, str(exc))
    finally:
        heartbeat.stop()


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


class CancelledError(RuntimeError):
    pass


ANALYZE_STAGES = ["stage2_media", "stage3_candidates", "auto_export"]


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
        fn()
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
        stage.error_message = None
        job.progress = progress
        job.progress_message = _stage_complete_message(name)
        session.commit()
        logger.info("Stage completed: job_id=%s stage=%s", job_id, name)


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


def _job_cancel_requested(bind, job_id: int) -> bool:
    factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
    with factory() as check_session:
        current = check_session.get(Job, job_id)
        return bool(
            current is not None
            and (current.cancel_requested or current.status == JobStatus.CANCEL_REQUESTED.value)
        )


class _LeaseHeartbeat:
    def __init__(self, bind, job_id: int, worker_id: str, interval_seconds: float = 20.0) -> None:
        self._factory = sessionmaker(bind=bind, expire_on_commit=False, autoflush=False)
        self._job_id = job_id
        self._worker_id = worker_id
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._thread = Thread(target=self._run, name=f"job-lease-{job_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            with self._factory() as lease_session:
                try:
                    if not heartbeat_job_lease(lease_session, self._job_id, self._worker_id):
                        logger.warning("Job heartbeat lost lease: job_id=%s", self._job_id)
                        return
                except Exception:
                    logger.exception("Job heartbeat failed: job_id=%s", self._job_id)
                    lease_session.rollback()


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
        if current is None or current.worker_id != _WORKER_ID:
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
        if current is None or current.worker_id != _WORKER_ID:
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


def _job_duration_seconds(job: Job) -> float | None:
    if job.started_at is None or job.finished_at is None:
        return None
    started = _aware(job.started_at)
    finished = _aware(job.finished_at)
    return (finished - started).total_seconds() if finished > started else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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

