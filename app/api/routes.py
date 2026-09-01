from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import (
    AutoCropResponse,
    AutoExportRequest,
    AutoExportResponse,
    CacheClearRequest,
    CacheRead,
    CandidateEditRequest,
    CandidateEditResponse,
    CandidateRead,
    CandidateSubtitlePayload,
    CandidateSubtitlesUpdate,
    CharacterCreate,
    CharacterMergeRequest,
    CharacterPhotoAdd,
    CharacterRead,
    CharacterRecognitionResponse,
    EnqueueSeasonRequest,
    ExportRead,
    ImportResponse,
    JobRead,
    ModelDiagnosticsRead,
    NarrationAudioRead,
    NarrationRead,
    ProjectDiagnosticsRead,
    PublishingPlanCreateRequest,
    PublishingPackageRead,
    PublishingPlanRead,
    PublishingPlanUpdateRequest,
    CandidateQualityRead,
    EpisodeOutlineRead,
    EpisodeQualityRead,
    PreviewRenderResponse,
    RenderRequest,
    RenderResponse,
    ReviewRequest,
    ReviewResponse,
    RuntimeSettingsRead,
    SeasonImportRequest,
    SeasonRead,
    Stage2RunResponse,
    Stage3RunResponse,
    SubtitleQualityRead,
    SpeakerIdentityRead,
    SpeakerIdentityUpdate,
    SpeakerLabelsRead,
    StoryArcCreateRequest,
    StoryArcCandidateAddRequest,
    StoryArcExportRead,
    StoryArcRead,
    StoryArcRenderJobResponse,
    StoryArcRenderRequest,
    StoryArcRenderResponse,
    StoryArcSegmentRead,
    StoryArcSegmentUpdateRequest,
    StoryContextRead,
    StoryContextUpdate,
    VideoScriptCreateRequest,
    VideoScriptRead,
    VideoScriptUpdateRequest,
    StoryArcUpdateRequest,
)
from app.application.candidate_editor import (
    EditableSubtitle,
    auto_split_candidate_subtitles,
    reset_candidate_subtitles,
    save_candidate_subtitles,
    subtitle_quality_report,
    subtitles_for_candidate,
)
from app.application.auto import auto_approve_and_export
from app.application.cache import cache_summary, clear_cache
from app.application.characters import (
    add_character_photo,
    assign_speaker_identity,
    merge_characters,
    recognize_episode_characters,
    train_character_voice,
)
from app.application.importer import import_season
from app.application.model_diagnostics import check_models
from app.application.narration import story_arc_narration, synthesize_story_arc_narration
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.project_diagnostics import run_project_diagnostics
from app.application.publishing import (
    create_publishing_package,
    PublishingPlanRequest,
    create_publishing_plan,
    list_publishing_plans,
    update_publishing_plan,
)
from app.api.dependencies import get_session
from app.application.quality_report import candidate_quality_report, episode_quality_report
from app.application.review import review_candidate, save_candidate_edits
from app.application.settings import RuntimeSettings, effective_settings, get_runtime_settings, save_runtime_settings
from app.application.stage4 import render_candidate, render_candidate_preview
from app.application.story_arcs import (
    StoryArcPlanRequest,
    StoryArcSegmentUpdate,
    StoryArcUpdate,
    add_candidate_to_story_arc,
    create_story_arc_plan,
    delete_story_arc,
    get_story_arc,
    list_story_arcs,
    rebuild_story_arc_plan,
    remove_story_arc_segment,
    update_story_arc,
    update_story_arc_segment,
)
from app.application.story_arc_render import render_story_arc
from app.application.system_check import report_as_dict, run_system_check
from app.application.video_scripts import (
    VideoScriptRequest,
    create_video_script,
    list_video_scripts,
    update_video_script,
)
from app.domain.enums import JobStatus
from app.media.ffprobe import apply_probe_to_episode, probe_media
from app.media.rendering import smooth_crop_keyframes
from app.models.entities import (
    Character,
    ClipCandidate,
    Episode,
    EpisodeOutline,
    Export,
    Job,
    PublishingPlan,
    Season,
    SpeakerIdentity,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    TranscriptSegment,
    VideoScript,
)
from app.infrastructure.config import get_settings
from app.workers.queue import (
    enqueue_candidate_render,
    enqueue_episode_analysis,
    enqueue_season_analysis,
    enqueue_story_arc_render,
)

router = APIRouter(prefix="/api")


def run_stage2_media_analysis(session: Session, episode_id: int, settings):
    """Lazy import seam kept patchable for API tests and light diagnostics."""
    from app.application.stage2 import run_stage2_media_analysis as run_stage2

    return run_stage2(session, episode_id, settings)


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
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arcs/{story_arc_id}", response_model=StoryArcRead)
def read_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        return _story_arc_read(session, get_story_arc(session, story_arc_id))
    except Exception as exc:
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
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/rebuild", response_model=StoryArcRead)
def rebuild_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        arc = rebuild_story_arc_plan(session, story_arc_id, effective_settings(session, get_settings()))
        session.commit()
        return _story_arc_read(session, arc)
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
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
            )
        session.commit()
        return result
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
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
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arcs/{story_arc_id}/narration", response_model=NarrationRead)
def read_story_arc_narration(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        return story_arc_narration(session, story_arc_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/story-arcs/{story_arc_id}/narration-audio", response_model=NarrationAudioRead)
def create_story_arc_narration_audio(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        audio = synthesize_story_arc_narration(session, story_arc_id, effective_settings(session, get_settings()))
        session.commit()
        return audio
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/story-arc-exports/{export_id}/file")
def story_arc_export_file(export_id: int, session: Session = Depends(get_session)):
    export = _get_story_arc_export(session, export_id)
    path = Path(export.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл StoryArc экспорта не найден")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/story-arc-exports/{export_id}/cover")
def story_arc_export_cover(export_id: int, session: Session = Depends(get_session)):
    export = _get_story_arc_export(session, export_id)
    if not export.cover_path:
        raise HTTPException(status_code=404, detail="Обложка StoryArc не создана")
    path = Path(export.cover_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл обложки StoryArc не найден")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.delete("/story-arcs/{story_arc_id}")
def remove_story_arc(story_arc_id: int, session: Session = Depends(get_session)):
    try:
        delete_story_arc(session, story_arc_id)
        session.commit()
        return {"deleted": True}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/publishing-plans/{plan_id}/package", response_model=PublishingPackageRead)
def package_publication(plan_id: int, session: Session = Depends(get_session)):
    try:
        settings = effective_settings(session, get_settings())
        path = create_publishing_package(session, plan_id, settings.output_dir)
        session.commit()
        return PublishingPackageRead(plan_id=plan_id, manifest_path=str(path))
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/project-diagnostics", response_model=ProjectDiagnosticsRead)
def project_diagnostics(session: Session = Depends(get_session)):
    return run_project_diagnostics(session, effective_settings(session, get_settings()))


@router.get("/seasons/{season_id}/characters", response_model=list[CharacterRead])
def list_characters(season_id: int, session: Session = Depends(get_session)):
    if session.get(Season, season_id) is None:
        raise HTTPException(status_code=404, detail="Сезон не найден")
    rows = session.scalars(select(Character).where(Character.season_id == season_id).order_by(Character.name)).all()
    return [_character_read(item) for item in rows]


@router.post("/seasons/{season_id}/characters", response_model=CharacterRead)
def create_character(
    season_id: int,
    payload: CharacterCreate,
    session: Session = Depends(get_session),
):
    if session.get(Season, season_id) is None:
        raise HTTPException(status_code=404, detail="Сезон не найден")
    try:
        character = Character(
            season_id=season_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
            aliases_json=[item.strip() for item in payload.aliases if item.strip()],
            color=payload.color,
        )
        session.add(character)
        session.flush()
        if payload.photo_data_url:
            add_character_photo(character, payload.photo_data_url, get_settings().characters_dir)
        session.commit()
        session.refresh(character)
        return _character_read(character)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/characters/{character_id}/photos", response_model=CharacterRead)
def add_character_reference_photo(
    character_id: int,
    payload: CharacterPhotoAdd,
    session: Session = Depends(get_session),
):
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Персонаж не найден")
    try:
        add_character_photo(character, payload.photo_data_url, get_settings().characters_dir)
        session.commit()
        return _character_read(character)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/characters/{character_id}/photos/{photo_index}")
def character_photo(character_id: int, photo_index: int, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if character is None or photo_index < 0 or photo_index >= len(character.photos_json or []):
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    path = Path(character.photos_json[photo_index]).resolve()
    root = get_settings().characters_dir.resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    return FileResponse(path)


@router.delete("/characters/{character_id}/photos/{photo_index}", response_model=CharacterRead)
def delete_character_photo(character_id: int, photo_index: int, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    photos = list(character.photos_json or []) if character is not None else []
    if character is None or photo_index < 0 or photo_index >= len(photos):
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    path = Path(photos.pop(photo_index)).resolve()
    root = get_settings().characters_dir.resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="Небезопасный путь фотографии")
    character.photos_json = photos
    session.commit()
    path.unlink(missing_ok=True)
    return _character_read(character)


@router.delete("/characters/{character_id}")
def delete_character(character_id: int, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Персонаж не найден")
    photo_paths = list(character.photos_json or [])
    session.execute(delete(SpeakerIdentity).where(SpeakerIdentity.character_id == character_id))
    session.delete(character)
    session.commit()
    root = get_settings().characters_dir.resolve()
    for raw_path in photo_paths:
        path = Path(raw_path).resolve()
        if root in path.parents:
            path.unlink(missing_ok=True)
    return {"deleted": True}


@router.post("/characters/{character_id}/merge", response_model=CharacterRead)
def merge_character_endpoint(
    character_id: int,
    payload: CharacterMergeRequest,
    session: Session = Depends(get_session),
):
    try:
        character = merge_characters(session, character_id, payload.target_character_id)
        session.commit()
        session.refresh(character)
        return _character_read(character)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/episodes/{episode_id}/speaker-identities", response_model=list[SpeakerIdentityRead])
def list_speaker_identities(episode_id: int, session: Session = Depends(get_session)):
    _get_episode(session, episode_id)
    rows = session.scalars(
        select(SpeakerIdentity)
        .where(SpeakerIdentity.episode_id == episode_id)
        .order_by(SpeakerIdentity.source_label)
    ).all()
    return [_speaker_identity_read(session, item) for item in rows]


@router.get("/episodes/{episode_id}/speaker-labels", response_model=SpeakerLabelsRead)
def list_speaker_labels(episode_id: int, session: Session = Depends(get_session)):
    _get_episode(session, episode_id)
    labels = {
        item
        for item in session.scalars(
            select(TranscriptSegment.speaker_label).where(TranscriptSegment.episode_id == episode_id)
        ).all()
        if item
    }
    return SpeakerLabelsRead(labels=sorted(labels))


@router.put("/episodes/{episode_id}/speaker-identities", response_model=SpeakerIdentityRead)
def update_speaker_identity(
    episode_id: int,
    payload: SpeakerIdentityUpdate,
    session: Session = Depends(get_session),
):
    try:
        _ensure_episode_not_enqueued(session, episode_id)
        identity = assign_speaker_identity(
            session,
            episode_id,
            payload.source_label,
            payload.character_id,
        )
        session.commit()
        with processing_guard():
            train_character_voice(session, episode_id, payload.source_label, payload.character_id)
        identity = session.scalar(
            select(SpeakerIdentity).where(
                SpeakerIdentity.episode_id == episode_id,
                SpeakerIdentity.source_label == payload.source_label,
            )
        )
        session.commit()
        if identity is None:
            raise ValueError("Не удалось сохранить привязку говорящего")
        return _speaker_identity_read(session, identity)
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/episodes/{episode_id}/identify-characters", response_model=CharacterRecognitionResponse)
def identify_episode_characters(episode_id: int, session: Session = Depends(get_session)):
    try:
        settings = effective_settings(session, get_settings())
        _ensure_episode_not_enqueued(session, episode_id)
        episode = _get_episode(session, episode_id)
        labels = {
            item
            for item in session.scalars(
                select(TranscriptSegment.speaker_label).where(TranscriptSegment.episode_id == episode_id)
            ).all()
            if item and item.startswith("Говорящий ")
        }
        session.commit()
        with processing_guard():
            result = recognize_episode_characters(session, episode.id, settings)
        session.commit()
        return CharacterRecognitionResponse(
            analyzed_labels=len(labels),
            assigned_labels=len(result.identities),
            assignments=[_speaker_identity_read(session, item) for item in result.identities],
            face_model=result.face_model,
            voice_profiles_used=result.voice_profiles_used,
        )
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        settings = effective_settings(session, get_settings())
        _ensure_episode_not_enqueued(session, episode_id)
        session.commit()
        with processing_guard():
            result = run_stage2_media_analysis(session, episode_id, settings)
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
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


@router.get("/candidates/{candidate_id}/quality", response_model=CandidateQualityRead)
def candidate_quality(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return candidate_quality_report(session, candidate_id)
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


@router.get("/candidates/{candidate_id}/subtitles/quality", response_model=SubtitleQualityRead)
def read_subtitle_quality(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return subtitle_quality_report(session, candidate_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/subtitles/auto-split", response_model=list[CandidateSubtitlePayload])
def auto_split_subtitles(candidate_id: int, session: Session = Depends(get_session)):
    try:
        result = auto_split_candidate_subtitles(session, candidate_id)
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/auto-crop", response_model=AutoCropResponse)
def auto_crop_candidate(candidate_id: int, session: Session = Depends(get_session)):
    from app.media.character_recognition import CharacterProfile
    from app.media.face_tracking import SpeechRange, estimate_face_offset

    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    try:
        settings = effective_settings(session, get_settings())
        _ensure_episode_not_enqueued(session, episode.id)
        identity_map = {
            item.source_label: item.character_id
            for item in session.scalars(
                select(SpeakerIdentity).where(SpeakerIdentity.episode_id == episode.id)
            ).all()
        }
        segments = session.scalars(
            select(TranscriptSegment).where(
                TranscriptSegment.episode_id == episode.id,
                TranscriptSegment.end_time >= candidate.start_time,
                TranscriptSegment.start_time <= candidate.end_time,
            )
        ).all()
        speech_ranges = [
            SpeechRange(
                item.start_time,
                item.end_time,
                item.speaker_label,
                identity_map.get(item.speaker_label) if item.speaker_label else None,
            )
            for item in segments
        ]
        characters = session.scalars(
            select(Character).where(Character.season_id == episode.season_id)
        ).all()
        profiles = [
            CharacterProfile(item.id, item.name, [Path(path) for path in item.photos_json or []])
            for item in characters
            if item.photos_json
        ]
        session.commit()
        with processing_guard():
            result = estimate_face_offset(
                Path(episode.proxy_path or episode.file_path),
                candidate.start_time,
                candidate.end_time,
                speech_ranges=speech_ranges,
                character_profiles=profiles,
                detector_model=settings.face_detector_model,
                recognizer_model=settings.face_recognizer_model,
                audio_path=Path(episode.audio_path) if episode.audio_path else None,
            )
        save_candidate_edits(
            session,
            candidate.id,
            crop_mode="auto-follow",
            crop_offset_x=result.offset_x,
        )
        candidate = session.get(ClipCandidate, candidate.id)
        candidate.crop_keyframes_json = smooth_crop_keyframes(result.keyframes)
        session.commit()
        return AutoCropResponse(
            candidate_id=candidate.id,
            crop_offset_x=candidate.crop_offset_x,
            faces_detected=result.faces_detected,
            frames_sampled=result.frames_sampled,
            keyframes=candidate.crop_keyframes_json,
            active_speaker_frames=result.active_speaker_frames,
            identified_speaker_frames=result.identified_speaker_frames,
            lip_motion_frames=result.lip_motion_frames,
            face_model=result.face_model,
            held_frames=result.held_frames,
            largest_face_frames=result.largest_face_frames,
            average_confidence=result.average_confidence,
        )
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/render", response_model=RenderResponse)
def render_candidate_endpoint(candidate_id: int, payload: RenderRequest, session: Session = Depends(get_session)):
    try:
        candidate = session.get(ClipCandidate, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        _ensure_episode_not_enqueued(session, candidate.episode_id)
        settings = effective_settings(session, get_settings())
        session.commit()
        with processing_guard():
            result = render_candidate(
                session,
                candidate_id,
                settings,
                payload.include_subtitles,
                payload.use_nvenc,
                payload.preset_name,
                payload.loudnorm_two_pass,
                payload.force_rerender,
            )
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.patch("/candidates/{candidate_id}", response_model=CandidateEditResponse)
def update_candidate_edits(
    candidate_id: int,
    payload: CandidateEditRequest,
    session: Session = Depends(get_session),
):
    try:
        result = save_candidate_edits(
            session,
            candidate_id,
            payload.adjusted_start_time,
            payload.adjusted_end_time,
            payload.crop_mode,
            payload.crop_offset_x,
            payload.crop_scale,
        )
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/preview", response_model=PreviewRenderResponse)
def render_candidate_preview_endpoint(
    candidate_id: int,
    payload: RenderRequest,
    session: Session = Depends(get_session),
):
    try:
        candidate = session.get(ClipCandidate, candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        _ensure_episode_not_enqueued(session, candidate.episode_id)
        settings = effective_settings(session, get_settings())
        session.commit()
        with processing_guard():
            result = render_candidate_preview(
                session,
                candidate_id,
                settings,
                include_subtitles=payload.include_subtitles,
            )
        session.commit()
        return PreviewRenderResponse(
            **result.__dict__,
            preview_url=f"/api/candidates/{candidate_id}/preview-file",
        )
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/preview-file")
def candidate_preview_file(candidate_id: int, session: Session = Depends(get_session)):
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    settings = effective_settings(session, get_settings())
    slug = f"preview-episode-{episode.id}-candidate-{candidate.id}.mp4"
    path = (settings.cache_dir / "previews" / episode.fingerprint / slug).resolve()
    root = (settings.cache_dir / "previews").resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="Preview ещё не создан")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


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
        _ensure_episode_not_enqueued(session, episode_id)
        session.commit()
        with processing_guard():
            result = auto_approve_and_export(
                session,
                episode_id,
                settings,
                threshold=payload.threshold if payload.threshold is not None else settings.auto_score_threshold,
                max_clips=payload.max_clips if payload.max_clips is not None else settings.max_clips_per_episode,
                use_nvenc=payload.use_nvenc if payload.use_nvenc is not None else settings.render_use_nvenc,
            )
        session.commit()
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


def _get_export(session: Session, export_id: int) -> Export:
    export = session.get(Export, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Экспорт не найден")
    return export


def _get_story_arc_export(session: Session, export_id: int) -> StoryArcExport:
    export = session.get(StoryArcExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="StoryArc export не найден")
    return export


def _get_episode(session: Session, episode_id: int) -> Episode:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    return episode


def _story_context_read(episode: Episode) -> StoryContextRead:
    return StoryContextRead(
        season_id=episode.season_id,
        episode_id=episode.id,
        season_context=episode.season.story_context,
        episode_summary=episode.story_summary,
        required_events=list(episode.required_events_json or []),
        excluded_events=list(episode.excluded_events_json or []),
        spoilers_allowed=episode.spoilers_allowed,
        candidate_mode=episode.candidate_mode,
    )


def _story_arc_read(session: Session, arc: StoryArc) -> StoryArcRead:
    season = session.get(Season, arc.season_id)
    character = session.get(Character, arc.target_character_id) if arc.target_character_id else None
    return StoryArcRead(
        id=arc.id,
        season_id=arc.season_id,
        season_title=season.title if season else "",
        title=arc.title,
        prompt=arc.prompt,
        arc_type=arc.arc_type,
        output_format=arc.output_format,
        target_character_id=arc.target_character_id,
        target_character_name=character.name if character else None,
        status=arc.status,
        total_duration_seconds=arc.total_duration_seconds,
        plan_json=arc.plan_json,
        segments=[_story_arc_segment_read(session, item) for item in arc.segments],
        exports=[_story_arc_export_read(item) for item in sorted(arc.exports, key=lambda export: export.id, reverse=True)],
    )


def _story_arc_segment_read(session: Session, segment: StoryArcSegment) -> StoryArcSegmentRead:
    episode = session.get(Episode, segment.episode_id)
    candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
    return StoryArcSegmentRead(
        id=segment.id,
        story_arc_id=segment.story_arc_id,
        episode_id=segment.episode_id,
        episode_file_name=episode.file_name if episode else "",
        candidate_id=segment.candidate_id,
        candidate_score=candidate.score if candidate else None,
        sort_order=segment.sort_order,
        start_time=segment.start_time,
        end_time=segment.end_time,
        title=segment.title,
        note=segment.note,
        role=segment.role,
    )


def _story_arc_export_read(export: StoryArcExport) -> StoryArcExportRead:
    return StoryArcExportRead(
        id=export.id,
        story_arc_id=export.story_arc_id,
        output_path=export.output_path,
        metadata_path=export.metadata_path,
        cover_path=export.cover_path,
        width=export.width,
        height=export.height,
        include_subtitles=export.include_subtitles,
        preset_name=export.preset_name,
        segment_count=export.segment_count,
        status=export.status,
        transition_style=export.transition_style,
        narration_included=export.narration_included,
    )


def _video_script_read(script: VideoScript) -> VideoScriptRead:
    return VideoScriptRead(
        id=script.id,
        season_id=script.season_id,
        story_arc_id=script.story_arc_id,
        title=script.title,
        prompt=script.prompt,
        style=script.style,
        script_text=script.script_text,
        structure_json=script.structure_json,
        status=script.status,
    )


def _publishing_plan_read(plan: PublishingPlan) -> PublishingPlanRead:
    return PublishingPlanRead(
        id=plan.id,
        season_id=plan.season_id,
        story_arc_id=plan.story_arc_id,
        story_arc_export_id=plan.story_arc_export_id,
        platform=plan.platform,
        title=plan.title,
        description=plan.description,
        hashtags=list(plan.hashtags_json or []),
        scheduled_for=plan.scheduled_for,
        status=plan.status,
    )


def _character_read(character: Character) -> CharacterRead:
    photos = list(character.photos_json or [])
    return CharacterRead(
        id=character.id,
        season_id=character.season_id,
        name=character.name,
        description=character.description,
        aliases=list(character.aliases_json or []),
        color=character.color,
        photo_count=len(photos),
        photo_urls=[f"/api/characters/{character.id}/photos/{index}" for index in range(len(photos))],
        voice_sample_count=int((character.voice_profile_json or {}).get("sample_count", 0)),
    )


def _speaker_identity_read(session: Session, identity: SpeakerIdentity) -> SpeakerIdentityRead:
    character = session.get(Character, identity.character_id)
    if character is None:
        raise HTTPException(status_code=409, detail="Привязанный персонаж не найден")
    return SpeakerIdentityRead(
        source_label=identity.source_label,
        character_id=character.id,
        character_name=character.name,
        confidence=identity.confidence,
        method=identity.method,
    )


def _ensure_episode_not_enqueued(session: Session, episode_id: int) -> None:
    active_job_id = session.scalar(
        select(Job.id).where(
            Job.episode_id == episode_id,
            Job.status.in_(
                [
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.PAUSED.value,
                    JobStatus.CANCEL_REQUESTED.value,
                ]
            ),
        ).limit(1)
    )
    if active_job_id is not None:
        raise ProcessingBusyError(
            f"Серия уже обрабатывается задачей №{active_job_id}. Используйте управление очередью."
        )
