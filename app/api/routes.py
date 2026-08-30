from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import (
    AutoCropResponse,
    AutoExportRequest,
    AutoExportResponse,
    CacheClearRequest,
    CacheRead,
    CandidateRead,
    CandidateSubtitlePayload,
    CandidateSubtitlesUpdate,
    EnqueueSeasonRequest,
    ExportRead,
    ImportResponse,
    JobRead,
    ModelDiagnosticsRead,
    QueueRunResponse,
    QueueStateResponse,
    RenderRequest,
    RenderResponse,
    ReviewRequest,
    ReviewResponse,
    RuntimeSettingsRead,
    SeasonImportRequest,
    SeasonRead,
    Stage2RunResponse,
    Stage3RunResponse,
)
from app.application.candidate_editor import (
    EditableSubtitle,
    reset_candidate_subtitles,
    save_candidate_subtitles,
    subtitles_for_candidate,
)
from app.application.auto import auto_approve_and_export
from app.application.cache import cache_summary, clear_cache
from app.application.importer import import_season
from app.application.model_diagnostics import check_models
from app.application.queue_control import get_queue_state, set_queue_paused
from app.application.review import review_candidate
from app.application.settings import RuntimeSettings, effective_settings, get_runtime_settings, save_runtime_settings
from app.application.stage2 import run_stage2_media_analysis
from app.application.stage3 import run_stage3_candidate_analysis
from app.application.stage4 import render_candidate
from app.application.system_check import report_as_dict, run_system_check
from app.infrastructure.database import SessionLocal
from app.media.ffprobe import apply_probe_to_episode, probe_media
from app.media.face_tracking import estimate_face_offset
from app.models.entities import ClipCandidate, Episode, Export, Job, Season
from app.infrastructure.config import get_settings
from app.workers.queue import enqueue_candidate_render, enqueue_episode_analysis, queue_snapshot, recover_interrupted_jobs
from app.workers.queue import enqueue_season_analysis, request_cancel, retry_job
from app.workers.runner import estimate_eta_seconds, run_next_job

router = APIRouter(prefix="/api")


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "SerialCuts"}


@router.get("/system-check")
def system_check() -> dict:
    return report_as_dict(run_system_check())


@router.get("/model-diagnostics", response_model=ModelDiagnosticsRead)
def model_diagnostics(session: Session = Depends(get_session)):
    return check_models(effective_settings(session, get_settings()))


@router.get("/cache", response_model=CacheRead)
def read_cache(session: Session = Depends(get_session)):
    return cache_summary(effective_settings(session, get_settings()).cache_dir)


@router.delete("/cache", response_model=CacheRead)
def delete_cache(payload: CacheClearRequest, session: Session = Depends(get_session)):
    try:
        return clear_cache(effective_settings(session, get_settings()).cache_dir, confirmed=payload.confirm)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/settings", response_model=RuntimeSettingsRead)
def read_settings(session: Session = Depends(get_session)):
    return get_runtime_settings(session, get_settings()).model_dump(mode="json")


@router.put("/settings", response_model=RuntimeSettingsRead)
def update_settings(payload: RuntimeSettings, session: Session = Depends(get_session)):
    result = save_runtime_settings(session, payload)
    session.commit()
    return result.model_dump(mode="json")


@router.post("/seasons/import", response_model=ImportResponse)
def import_season_endpoint(payload: SeasonImportRequest, session: Session = Depends(get_session)):
    try:
        result = import_season(session, payload.root_path, payload.title)
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(
        season_id=result.season.id,
        created=result.created,
        skipped_duplicates=result.skipped_duplicates,
        episode_ids=result.episode_ids,
    )


@router.get("/seasons", response_model=list[SeasonRead])
def list_seasons(session: Session = Depends(get_session)):
    seasons = session.scalars(select(Season).options(selectinload(Season.episodes))).all()
    return seasons


@router.post("/episodes/{episode_id}/probe")
def probe_episode(episode_id: int, session: Session = Depends(get_session)):
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    try:
        summary = probe_media(get_settings().ffprobe_path, media_path=Path(episode.file_path))
        apply_probe_to_episode(episode, summary)
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "stage": episode.stage}


@router.post("/episodes/{episode_id}/enqueue", response_model=JobRead)
def enqueue_episode(episode_id: int, session: Session = Depends(get_session)):
    try:
        job = enqueue_episode_analysis(session, episode_id)
        session.commit()
        session.refresh(job)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job


@router.post("/seasons/{season_id}/enqueue", response_model=list[JobRead])
def enqueue_season(season_id: int, payload: EnqueueSeasonRequest, session: Session = Depends(get_session)):
    try:
        jobs = enqueue_season_analysis(session, season_id, auto=payload.auto)
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jobs


@router.post("/episodes/{episode_id}/stage2", response_model=Stage2RunResponse)
def run_stage2_episode(episode_id: int, session: Session = Depends(get_session)):
    try:
        result = run_stage2_media_analysis(session, episode_id, effective_settings(session, get_settings()))
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/episodes/{episode_id}/stage3", response_model=Stage3RunResponse)
def run_stage3_episode(episode_id: int, session: Session = Depends(get_session)):
    try:
        result = run_stage3_candidate_analysis(session, episode_id, effective_settings(session, get_settings()))
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/episodes/{episode_id}/candidates", response_model=list[CandidateRead])
def list_episode_candidates(episode_id: int, session: Session = Depends(get_session)):
    return session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id == episode_id).order_by(ClipCandidate.score.desc())
    ).all()


@router.get("/episodes/{episode_id}/proxy")
def episode_proxy(episode_id: int, session: Session = Depends(get_session)):
    episode = session.get(Episode, episode_id)
    if episode is None or not episode.proxy_path:
        raise HTTPException(status_code=404, detail="Proxy ещё не создан")
    path = Path(episode.proxy_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Proxy-файл не найден")
    return FileResponse(path, media_type="video/mp4")


@router.post("/candidates/{candidate_id}/review", response_model=ReviewResponse)
def review_candidate_endpoint(candidate_id: int, payload: ReviewRequest, session: Session = Depends(get_session)):
    try:
        result = review_candidate(
            session,
            candidate_id,
            payload.decision,
            payload.adjusted_start_time,
            payload.adjusted_end_time,
            payload.crop_mode,
            payload.crop_offset_x,
            payload.crop_scale,
            payload.reason,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/candidates/{candidate_id}/subtitles", response_model=list[CandidateSubtitlePayload])
def read_candidate_subtitles(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return subtitles_for_candidate(session, candidate_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/candidates/{candidate_id}/subtitles", response_model=list[CandidateSubtitlePayload])
def update_candidate_subtitles(
    candidate_id: int,
    payload: CandidateSubtitlesUpdate,
    session: Session = Depends(get_session),
):
    try:
        result = save_candidate_subtitles(
            session,
            candidate_id,
            [EditableSubtitle(**item.model_dump()) for item in payload.subtitles],
        )
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/candidates/{candidate_id}/subtitles", response_model=list[CandidateSubtitlePayload])
def reset_candidate_subtitles_endpoint(candidate_id: int, session: Session = Depends(get_session)):
    try:
        result = reset_candidate_subtitles(session, candidate_id)
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/auto-crop", response_model=AutoCropResponse)
def auto_crop_candidate(candidate_id: int, session: Session = Depends(get_session)):
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    try:
        result = estimate_face_offset(Path(episode.file_path), candidate.start_time, candidate.end_time)
        candidate.crop_mode = "auto-follow"
        candidate.crop_offset_x = result.offset_x
        session.commit()
        return AutoCropResponse(
            candidate_id=candidate.id,
            crop_offset_x=candidate.crop_offset_x,
            faces_detected=result.faces_detected,
            frames_sampled=result.frames_sampled,
        )
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/render", response_model=RenderResponse)
def render_candidate_endpoint(candidate_id: int, payload: RenderRequest, session: Session = Depends(get_session)):
    try:
        result = render_candidate(
            session,
            candidate_id,
            effective_settings(session, get_settings()),
            payload.include_subtitles,
            payload.use_nvenc,
            payload.preset_name,
            payload.loudnorm_two_pass,
            payload.force_rerender,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/candidates/{candidate_id}/render-job", response_model=JobRead)
def enqueue_candidate_render_endpoint(
    candidate_id: int,
    payload: RenderRequest,
    session: Session = Depends(get_session),
):
    try:
        job = enqueue_candidate_render(session, candidate_id, payload.model_dump())
        session.commit()
        session.refresh(job)
        return job
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/exports", response_model=list[ExportRead])
def list_exports(session: Session = Depends(get_session)):
    return session.scalars(select(Export).order_by(Export.created_at.desc())).all()


@router.get("/exports/{export_id}/file")
def export_file(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    path = Path(export.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл экспорта не найден")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/exports/{export_id}/cover")
def export_cover(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    if not export.cover_path:
        raise HTTPException(status_code=404, detail="Обложка не создана")
    path = Path(export.cover_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл обложки не найден")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.post("/exports/{export_id}/open-folder")
def open_export_folder(export_id: int, session: Session = Depends(get_session)):
    export = _get_export(session, export_id)
    path = Path(export.output_path).resolve(strict=False)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл экспорта не найден")
    try:
        os.startfile(path.parent)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "folder": str(path.parent)}


@router.post("/episodes/{episode_id}/auto-export", response_model=AutoExportResponse)
def auto_export_episode(episode_id: int, payload: AutoExportRequest, session: Session = Depends(get_session)):
    settings = effective_settings(session, get_settings())
    try:
        result = auto_approve_and_export(
            session,
            episode_id,
            settings,
            threshold=payload.threshold if payload.threshold is not None else settings.auto_score_threshold,
            max_clips=payload.max_clips if payload.max_clips is not None else settings.max_clips_per_episode,
            use_nvenc=payload.use_nvenc if payload.use_nvenc is not None else settings.render_use_nvenc,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/jobs/recover")
def recover_jobs(session: Session = Depends(get_session)):
    count = recover_interrupted_jobs(session)
    session.commit()
    return {"recovered": count}


@router.post("/queue/run-next", response_model=QueueRunResponse)
def run_queue_next(session: Session = Depends(get_session)):
    result = run_next_job(session, effective_settings(session, get_settings()))
    session.commit()
    return result


@router.post("/queue/pause", response_model=QueueStateResponse)
def pause_queue(session: Session = Depends(get_session)):
    state = set_queue_paused(session, True)
    session.commit()
    return {"state": state}


@router.post("/queue/resume", response_model=QueueStateResponse)
def resume_queue(session: Session = Depends(get_session)):
    state = set_queue_paused(session, False)
    session.commit()
    return {"state": state}


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = request_cancel(session, job_id)
    session.commit()
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job_endpoint(job_id: int, session: Session = Depends(get_session)):
    job = retry_job(session, job_id)
    session.commit()
    return job


@router.get("/jobs")
def jobs(session: Session = Depends(get_session)):
    snapshot = queue_snapshot(session)
    snapshot = snapshot.__class__(
        queued=snapshot.queued,
        running=snapshot.running,
        failed=snapshot.failed,
        paused=get_queue_state(session) == "paused",
        eta_seconds=estimate_eta_seconds(session),
    )
    items = session.scalars(select(Job).order_by(Job.updated_at.desc())).all()
    return {"snapshot": snapshot.__dict__, "items": items}


def _get_export(session: Session, export_id: int) -> Export:
    export = session.get(Export, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Экспорт не найден")
    return export
