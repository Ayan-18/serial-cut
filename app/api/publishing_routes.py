from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api._shared import _publishing_plan_read, _video_script_read
from app.api.dependencies import get_session
from app.api.schemas import PublishingPackageRead, PublishingPlanCreateRequest, PublishingPlanRead, PublishingPlanUpdateRequest, VideoScriptCreateRequest, VideoScriptRead, VideoScriptUpdateRequest
from app.application.publishing import PublishingPlanRequest, create_publishing_package, create_publishing_plan, list_publishing_plans, update_publishing_plan
from app.application.settings import effective_settings
from app.application.video_scripts import VideoScriptRequest, create_video_script, list_video_scripts, update_video_script
from app.infrastructure.config import get_settings

router = APIRouter(prefix="/api")

@router.get("/video-scripts", response_model=list[VideoScriptRead])
def video_scripts(season_id: int | None = None, session: Session = Depends(get_session)):
    return [_video_script_read(item) for item in list_video_scripts(session, season_id)]


@router.post("/video-scripts", response_model=VideoScriptRead)
def create_script(payload: VideoScriptCreateRequest, session: Session = Depends(get_session)):
    try:
        script = create_video_script(
            session,
            VideoScriptRequest(**payload.model_dump()),
            effective_settings(session, get_settings()),
        )
        session.commit()
        return _video_script_read(script)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/video-scripts/{script_id}", response_model=VideoScriptRead)
def patch_script(script_id: int, payload: VideoScriptUpdateRequest, session: Session = Depends(get_session)):
    try:
        script = update_video_script(
            session,
            script_id,
            payload.title,
            payload.script_text,
            payload.status,
        )
        session.commit()
        return _video_script_read(script)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/publishing-plans", response_model=list[PublishingPlanRead])
def publishing_plans(season_id: int | None = None, session: Session = Depends(get_session)):
    return [_publishing_plan_read(item) for item in list_publishing_plans(session, season_id)]


@router.post("/publishing-plans", response_model=PublishingPlanRead)
def create_publication(payload: PublishingPlanCreateRequest, session: Session = Depends(get_session)):
    try:
        plan = create_publishing_plan(session, PublishingPlanRequest(**payload.model_dump()))
        session.commit()
        return _publishing_plan_read(plan)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/publishing-plans/{plan_id}", response_model=PublishingPlanRead)
def patch_publication(plan_id: int, payload: PublishingPlanUpdateRequest, session: Session = Depends(get_session)):
    try:
        plan = update_publishing_plan(
            session,
            plan_id,
            title=payload.title,
            description=payload.description,
            hashtags=payload.hashtags,
            scheduled_for=payload.scheduled_for,
            status=payload.status,
        )
        session.commit()
        return _publishing_plan_read(plan)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/publishing-plans/{plan_id}/package", response_model=PublishingPackageRead)
def package_publication(plan_id: int, session: Session = Depends(get_session)):
    try:
        settings = effective_settings(session, get_settings())
        path = create_publishing_package(session, plan_id, settings.output_dir)
        session.commit()
        return PublishingPackageRead(plan_id=plan_id, manifest_path=str(path))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

