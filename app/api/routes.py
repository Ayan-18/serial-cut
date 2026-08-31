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
    CandidateRead,
    CandidateSubtitlePayload,
    CandidateSubtitlesUpdate,
    CharacterCreate,
    CharacterPhotoAdd,
    CharacterRead,
    CharacterRecognitionResponse,
    EnqueueSeasonRequest,
    ExportRead,
    ImportResponse,
    JobRead,
    ModelDiagnosticsRead,
    EpisodeOutlineRead,
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
    SpeakerIdentityRead,
    SpeakerIdentityUpdate,
    SpeakerLabelsRead,
    StoryContextRead,
    StoryContextUpdate,
)
from app.application.candidate_editor import (
    EditableSubtitle,
    reset_candidate_subtitles,
    save_candidate_subtitles,
    subtitles_for_candidate,
)
from app.application.auto import auto_approve_and_export
from app.application.cache import cache_summary, clear_cache
from app.application.characters import (
    add_character_photo,
    assign_speaker_identity,
    recognize_episode_characters,
    train_character_voice,
)
from app.application.importer import import_season
from app.application.model_diagnostics import check_models
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.application.queue_control import get_queue_state, set_queue_paused
from app.application.review import review_candidate
from app.application.settings import RuntimeSettings, effective_settings, get_runtime_settings, save_runtime_settings
from app.application.stage2 import run_stage2_media_analysis
from app.application.stage3 import run_stage3_candidate_analysis
from app.application.stage4 import render_candidate
from app.application.system_check import report_as_dict, run_system_check
from app.domain.enums import JobStatus
from app.infrastructure.database import SessionLocal
from app.media.ffprobe import apply_probe_to_episode, probe_media
from app.media.character_recognition import CharacterProfile
from app.media.face_tracking import SpeechRange, estimate_face_offset
from app.models.entities import (
    Character,
    ClipCandidate,
    Episode,
    EpisodeOutline,
    Export,
    Job,
    Season,
    SpeakerIdentity,
    TranscriptSegment,
)
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
            )
        candidate.crop_mode = "auto-follow"
        candidate.crop_offset_x = result.offset_x
        candidate.crop_keyframes_json = result.keyframes
        session.commit()
        return AutoCropResponse(
            candidate_id=candidate.id,
            crop_offset_x=candidate.crop_offset_x,
            faces_detected=result.faces_detected,
            frames_sampled=result.frames_sampled,
            keyframes=result.keyframes,
            active_speaker_frames=result.active_speaker_frames,
            identified_speaker_frames=result.identified_speaker_frames,
            lip_motion_frames=result.lip_motion_frames,
            face_model=result.face_model,
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
