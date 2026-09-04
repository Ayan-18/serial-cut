from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api._shared import _get_story_arc_export, _story_arc_read
from app.api.dependencies import get_session
from app.api.media_files import safe_file_response
from app.api.schemas import NarrationAudioRead, NarrationRead, StoryArcCandidateAddRequest, StoryArcCreateRequest, StoryArcRead, StoryArcRenderJobResponse, StoryArcRenderRequest, StoryArcRenderResponse, StoryArcSegmentUpdateRequest, StoryArcUpdateRequest
from app.application.derived_files import delete_derived_artifacts, delete_derived_tree
from app.application.narration import story_arc_narration, synthesize_story_arc_narration
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.settings import effective_settings
from app.application.story_arc_render import render_story_arc
from app.application.story_arcs import StoryArcPlanRequest, StoryArcSegmentUpdate, StoryArcUpdate, add_candidate_to_story_arc, create_story_arc_plan, delete_story_arc, get_story_arc, list_story_arcs, rebuild_story_arc_plan, remove_story_arc_segment, update_story_arc, update_story_arc_segment
from app.infrastructure.config import get_settings
from app.workers.queue import enqueue_story_arc_render

router = APIRouter(prefix="/api")

@router.get("/story-arcs", response_model=list[StoryArcRead])
def story_arcs(season_id: int | None = None, session: Session = Depends(get_session)):
    return [_story_arc_read(session, item) for item in list_story_arcs(session, season_id)]


@router.post("/story-arcs", response_model=StoryArcRead)
def create_story_arc(payload: StoryArcCreateRequest, session: Session = Depends(get_session)):
    try:
        arc = create_story_arc_plan(
            session,
            StoryArcPlanRequest(**payload.model_dump()),
            effective_settings(session, get_settings()),
        )
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arcs/{story_arc_id}", response_model=StoryArcRead)
def read_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        return _story_arc_read(session, get_story_arc(session, story_arc_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/story-arcs/{story_arc_id}", response_model=StoryArcRead)
def patch_story_arc(
    story_arc_id: int,
    payload: StoryArcUpdateRequest,
    session: Session = Depends(get_session),
):
    try:
        arc = update_story_arc(session, story_arc_id, StoryArcUpdate(**payload.model_dump(exclude_unset=True)))
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/rebuild", response_model=StoryArcRead)
def rebuild_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        arc = rebuild_story_arc_plan(session, story_arc_id, effective_settings(session, get_settings()))
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/story-arcs/{story_arc_id}/segments/{segment_id}", response_model=StoryArcRead)
def patch_story_arc_segment(
    story_arc_id: int,
    segment_id: int,
    payload: StoryArcSegmentUpdateRequest,
    session: Session = Depends(get_session),
):
    try:
        arc = update_story_arc_segment(
            session,
            story_arc_id,
            segment_id,
            StoryArcSegmentUpdate(**payload.model_dump(exclude_unset=True)),
        )
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/story-arcs/{story_arc_id}/segments/{segment_id}", response_model=StoryArcRead)
def delete_story_arc_segment(
    story_arc_id: int,
    segment_id: int,
    session: Session = Depends(get_session),
):
    try:
        arc = remove_story_arc_segment(session, story_arc_id, segment_id)
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/segments", response_model=StoryArcRead)
def add_story_arc_segment(
    story_arc_id: int,
    payload: StoryArcCandidateAddRequest,
    session: Session = Depends(get_session),
):
    try:
        arc = add_candidate_to_story_arc(session, story_arc_id, payload.candidate_id)
        session.commit()
        return _story_arc_read(session, arc)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/render", response_model=StoryArcRenderResponse)
def render_story_arc_endpoint(
    story_arc_id: int,
    payload: StoryArcRenderRequest,
    session: Session = Depends(get_session),
):
    try:
        settings = effective_settings(session, get_settings())
        session.commit()
        with processing_guard():
            result = render_story_arc(
                session,
                story_arc_id,
                settings,
                include_subtitles=payload.include_subtitles,
                use_nvenc=payload.use_nvenc,
                preset_name=payload.preset_name,
                loudnorm_two_pass=payload.loudnorm_two_pass,
                force_rerender=payload.force_rerender,
                transition_style=payload.transition_style,
                include_narration=payload.include_narration,
                narration_mode=payload.narration_mode,
            )
        session.commit()
        return result
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/render-job", response_model=StoryArcRenderJobResponse)
def enqueue_story_arc_render_endpoint(
    story_arc_id: int,
    payload: StoryArcRenderRequest,
    session: Session = Depends(get_session),
):
    try:
        job = enqueue_story_arc_render(session, story_arc_id, payload.model_dump())
        session.commit()
        return StoryArcRenderJobResponse(job=job)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arcs/{story_arc_id}/narration", response_model=NarrationRead)
def read_story_arc_narration(
    story_arc_id: int,
    narration_mode: str = "first_person",
    session: Session = Depends(get_session),
):
    try:
        return story_arc_narration(session, story_arc_id, narration_mode=narration_mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/narration-audio", response_model=NarrationAudioRead)
def create_story_arc_narration_audio(
    story_arc_id: int,
    narration_mode: str = "first_person",
    session: Session = Depends(get_session),
):
    try:
        audio = synthesize_story_arc_narration(
            session,
            story_arc_id,
            effective_settings(session, get_settings()),
            narration_mode=narration_mode,
        )
        session.commit()
        return audio
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arcs/{story_arc_id}/narration-audio-file")
def story_arc_narration_audio_file(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        arc = get_story_arc(session, story_arc_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    settings = effective_settings(session, get_settings())
    return safe_file_response(
        settings,
        (arc.plan_json or {}).get("narration_audio_path"),
        media_type="audio/wav",
        missing_detail="Озвучка ещё не создана",
    )


@router.get("/story-arc-exports/{export_id}/file")
def story_arc_export_file(export_id: int, session: Session = Depends(get_session)):
    export = _get_story_arc_export(session, export_id)
    settings = effective_settings(session, get_settings())
    return safe_file_response(
        settings,
        export.output_path,
        media_type="video/mp4",
        missing_detail="Файл StoryArc экспорта не найден",
    )


@router.get("/story-arc-exports/{export_id}/cover")
def story_arc_export_cover(export_id: int, session: Session = Depends(get_session)):
    export = _get_story_arc_export(session, export_id)
    settings = effective_settings(session, get_settings())
    return safe_file_response(
        settings,
        export.cover_path,
        media_type="image/jpeg",
        missing_detail="Файл обложки StoryArc не найден",
    )


@router.delete("/story-arcs/{story_arc_id}")
def remove_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        settings = effective_settings(session, get_settings())
        artifacts = delete_story_arc(session, story_arc_id)
        session.commit()
        delete_derived_artifacts(artifacts.paths, [settings.output_dir, settings.cache_dir])
        delete_derived_tree(
            settings.cache_dir / "story-arc-segments" / str(story_arc_id),
            [settings.cache_dir],
        )
        for plan_id in artifacts.publishing_plan_ids:
            delete_derived_tree(
                settings.output_dir / "publishing" / f"plan-{plan_id}",
                [settings.output_dir],
            )
        return {"deleted": True}
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

