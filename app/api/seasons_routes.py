from __future__ import annotations

from app.api._shared import *  # noqa: F403

router = APIRouter(prefix="/api")

@router.post("/seasons/import", response_model=ImportResponse)
def import_season_endpoint(payload: SeasonImportRequest, session: Session = Depends(get_session)):
    try:
        result = import_season(session, payload.root_path, payload.title)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportResponse(
        season_id=result.season.id,
        created=result.created,
        skipped_duplicates=result.skipped_duplicates,
        episode_ids=result.episode_ids,
        scanned=result.scanned,
        errors=[{"file_name": item.file_name, "reason": item.reason} for item in result.errors],
    )


@router.get("/seasons", response_model=list[SeasonRead])
def list_seasons(session: Session = Depends(get_session)):
    seasons = session.scalars(select(Season).options(selectinload(Season.episodes))).all()
    return seasons


@router.get("/episodes/{episode_id}/story-context", response_model=StoryContextRead)
def read_story_context(episode_id: int, session: Session = Depends(get_session)):
    episode = _get_episode(session, episode_id)
    return _story_context_read(episode)


@router.put("/episodes/{episode_id}/story-context", response_model=StoryContextRead)
def update_story_context(
    episode_id: int,
    payload: StoryContextUpdate,
    session: Session = Depends(get_session),
):
    episode = _get_episode(session, episode_id)
    episode.season.story_context = payload.season_context.strip()
    episode.story_summary = payload.episode_summary.strip()
    episode.required_events_json = [item.strip() for item in payload.required_events if item.strip()]
    episode.excluded_events_json = [item.strip() for item in payload.excluded_events if item.strip()]
    episode.spoilers_allowed = payload.spoilers_allowed
    episode.candidate_mode = payload.candidate_mode
    session.commit()
    return _story_context_read(episode)


@router.get("/episodes/{episode_id}/outline", response_model=EpisodeOutlineRead)
def read_episode_outline(episode_id: int, session: Session = Depends(get_session)):
    _get_episode(session, episode_id)
    outline = session.scalar(select(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    if outline is None:
        raise HTTPException(status_code=404, detail="Сюжетная карта ещё не построена")
    return EpisodeOutlineRead(episode_id=episode_id, summary_json=outline.summary_json)

