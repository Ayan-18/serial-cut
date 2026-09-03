from __future__ import annotations

from app.api._shared import *  # noqa: F403

router = APIRouter(prefix="/api")

def run_stage2_media_analysis(session: Session, episode_id: int, settings):
    """Lazy import seam kept patchable for API tests and light diagnostics."""
    from app.application.stage2 import run_stage2_media_analysis as run_stage2

    return run_stage2(session, episode_id, settings)

@router.post("/episodes/{episode_id}/probe")
def probe_episode(episode_id: int, session: Session = Depends(get_session)):
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    try:
        summary = probe_media(get_settings().ffprobe_path, media_path=Path(episode.file_path))
        apply_probe_to_episode(episode, summary)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "stage": episode.stage}


@router.delete("/episodes/{episode_id}")
def delete_episode_endpoint(episode_id: int, session: Session = Depends(get_session)):
    settings = effective_settings(session, get_settings())
    try:
        artifacts = delete_episode(session, episode_id, settings)
        session.commit()
    except ResourceBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    purge_artifacts(artifacts, settings)
    return {"deleted": True}


@router.post("/episodes/{episode_id}/enqueue", response_model=JobRead)
def enqueue_episode(
    episode_id: int,
    payload: EnqueueEpisodeRequest | None = None,
    session: Session = Depends(get_session),
):
    try:
        job_payload = payload.model_dump(exclude_none=True) if payload else None
        job = enqueue_episode_analysis(session, episode_id, payload=job_payload)
        session.commit()
        session.refresh(job)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job


@router.post("/seasons/{season_id}/enqueue", response_model=list[JobRead])
def enqueue_season(season_id: int, payload: EnqueueSeasonRequest, session: Session = Depends(get_session)):
    try:
        jobs = enqueue_season_analysis(session, season_id, auto=payload.auto)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return jobs


@router.post("/episodes/{episode_id}/stage2", response_model=Stage2RunResponse)
def run_stage2_episode(episode_id: int, session: Session = Depends(get_session)):
    try:
        settings = effective_settings(session, get_settings())
        _ensure_episode_not_enqueued(session, episode_id)
        session.commit()
        with processing_guard():
            result = run_stage2_media_analysis(session, episode_id, settings)
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/episodes/{episode_id}/stage3", response_model=Stage3RunResponse)
def run_stage3_episode(episode_id: int, session: Session = Depends(get_session)):
    try:
        from app.application.stage3 import run_stage3_candidate_analysis

        settings = effective_settings(session, get_settings())
        _ensure_episode_not_enqueued(session, episode_id)
        session.commit()
        with processing_guard():
            result = run_stage3_candidate_analysis(session, episode_id, settings)
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/episodes/{episode_id}/candidates", response_model=list[CandidateRead])
def list_episode_candidates(episode_id: int, session: Session = Depends(get_session)):
    episode = _get_episode(session, episode_id)
    order = (
        (ClipCandidate.story_order.asc(), ClipCandidate.start_time.asc())
        if episode.candidate_mode == "story"
        else (ClipCandidate.score.desc(),)
    )
    return session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id == episode_id).order_by(*order)
    ).all()


@router.get("/episodes/{episode_id}/quality", response_model=EpisodeQualityRead)
def episode_quality(episode_id: int, session: Session = Depends(get_session)):
    try:
        return episode_quality_report(session, episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/episodes/{episode_id}/proxy")
def episode_proxy(episode_id: int, session: Session = Depends(get_session)):
    episode = session.get(Episode, episode_id)
    if episode is None or not episode.proxy_path:
        raise HTTPException(status_code=404, detail="Proxy ещё не создан")
    path = Path(episode.proxy_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Proxy-файл не найден")
    return FileResponse(path, media_type="video/mp4")


