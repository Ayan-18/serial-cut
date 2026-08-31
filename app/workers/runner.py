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
from app.application.stage4 import render_candidate
from app.application.story_arc_render import render_story_arc
from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.infrastructure.database import SessionLocal
from app.infrastructure.processes import ProcessCancelledError, run_process_cancellable
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
    stage2_func: Stage2Func | None = None,
    stage3_func: Stage3Func | None = None,
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
    stage2_func: Stage2Func | None,
    stage3_func: Stage3Func | None,
) -> WorkerRunResult:
    if get_queue_state(session) == "paused":
        return WorkerRunResult(False, None, "paused", "Очередь на паузе")
    job = next_queued_job(session)
    if job is None:
        return WorkerRunResult(False, None, "idle", "Нет задач в очереди")
    if job.episode_id is None and job.kind != JobKind.RENDER_STORY_ARC.value:
        job.status = JobStatus.FAILED.value
        job.error_message = "У job нет episode_id"
        return WorkerRunResult(True, job.id, job.status, job.error_message)

    job.status = JobStatus.RUNNING.value
    job.error_message = None
    payload = job.payload or {}
    resume_from_stage = str(payload.get("resume_from_stage") or "")
    job.progress = _resume_progress(resume_from_stage)
    session.commit()
    started = monotonic()
    try:
        cancellable_runner = lambda args, timeout: run_process_cancellable(
            args,
            timeout,
            lambda: _job_cancel_requested(job.id),
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
                    progress_callback=lambda current, total, _message: _update_render_progress(
                        session, job, current, total
                    ),
                    cancel_check=lambda: _job_cancel_requested(job.id),
                    runner=cancellable_runner,
                ),
                0.95,
            )
        else:
            if stage2_func is None or stage3_func is None:
                from app.application.stage2 import run_stage2_media_analysis
                from app.application.stage3 import run_stage3_candidate_analysis

                stage2_func = stage2_func or run_stage2_media_analysis
                stage3_func = stage3_func or run_stage3_candidate_analysis
            if resume_from_stage and resume_from_stage not in ANALYZE_STAGES:
                raise ValueError(f"Неизвестный этап анализа: {resume_from_stage}")
            resume_stage = resume_from_stage or "stage2_media"
            if _should_run_analyze_stage("stage2_media", resume_stage):
                _run_stage(session, job, "stage2_media", lambda: stage2_func(session, job.episode_id, settings), 0.45)
                _raise_if_cancelled(session, job)
            if _should_run_analyze_stage("stage3_candidates", resume_stage):
                _run_stage(session, job, "stage3_candidates", lambda: stage3_func(session, job.episode_id, settings), 0.75)
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
    stage = _get_or_create_stage(session, job, name)
    stage.status = JobStatus.RUNNING.value
    stage.started_at = datetime.now(timezone.utc).isoformat()
    job.current_stage = name
    session.commit()
    try:
        fn()
    except ProcessCancelledError as exc:
        stage.status = JobStatus.PAUSED.value
        stage.finished_at = datetime.now(timezone.utc).isoformat()
        stage.error_message = str(exc)
        session.commit()
        raise CancelledError(str(exc)) from exc
    except Exception as exc:
        stage.status = JobStatus.FAILED.value
        stage.finished_at = datetime.now(timezone.utc).isoformat()
        stage.error_message = str(exc)
        session.commit()
        raise
    else:
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


def _job_cancel_requested(job_id: int) -> bool:
    with SessionLocal() as check_session:
        current = check_session.get(Job, job_id)
        return bool(
            current is not None
            and (current.cancel_requested or current.status == JobStatus.CANCEL_REQUESTED.value)
        )


def _update_render_progress(session: Session, job: Job, current: int, total: int) -> None:
    if total <= 0:
        return
    job.progress = min(0.94, max(0.02, 0.02 + 0.92 * current / total))
    session.commit()

