from __future__ import annotations

from dataclasses import dataclass
import logging
from time import monotonic
from typing import Callable
from threading import Lock

from sqlalchemy.orm import Session

from app.application.auto import auto_approve_and_export
from app.application.queue_control import get_queue_state
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.stage4 import render_candidate
from app.application.story_arc_render import render_story_arc
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.infrastructure.processes import run_process_cancellable
from app.workers.job_stages import (
    ANALYZE_STAGES,
    CancelledError,
    _raise_if_cancelled,
    _record_job_terminal,
    _resume_progress,
    _run_stage,
    _should_run_analyze_stage,
    _update_analysis_progress,
    _update_render_progress,
    estimate_eta_seconds,
)
from app.workers.lease import _job_cancel_requested, _LeaseHeartbeat
from app.workers.queue import claim_next_queued_job, recover_interrupted_jobs
from app.workers.worker_identity import WORKER_ID

# Re-exported: estimate_eta_seconds used to be defined in this module and a
# test still imports it from here. The job/stage bookkeeping it lives next to
# now (recording terminal states, resume-from-stage, progress messages) moved
# to job_stages.py; the lease heartbeat moved to lease.py. Neither touches
# `render_candidate`, which is why `_run_next_job_unlocked` — the thing tests
# monkeypatch that name on — stayed here.
__all__ = ["WorkerRunResult", "run_next_job", "estimate_eta_seconds"]

logger = logging.getLogger(__name__)


Stage2Func = Callable[..., object]
Stage3Func = Callable[..., object]


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
    job = claim_next_queued_job(session, WORKER_ID)
    if job is None:
        logger.debug("Worker run skipped: no queued jobs")
        return WorkerRunResult(False, None, "idle", "Нет задач в очереди")
    logger.info("Claimed job: id=%s kind=%s episode_id=%s", job.id, job.kind, job.episode_id)
    heartbeat = _LeaseHeartbeat(session.get_bind(), job.id, WORKER_ID)
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
