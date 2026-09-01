from __future__ import annotations

from app.api._shared import *  # noqa: F403

router = APIRouter(prefix="/api")

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
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/candidates/{candidate_id}/subtitles", response_model=list[CandidateSubtitlePayload])
def read_candidate_subtitles(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return subtitles_for_candidate(session, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/quality", response_model=CandidateQualityRead)
def candidate_quality(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return candidate_quality_report(session, candidate_id)
    except ValueError as exc:
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
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/candidates/{candidate_id}/subtitles", response_model=list[CandidateSubtitlePayload])
def reset_candidate_subtitles_endpoint(candidate_id: int, session: Session = Depends(get_session)):
    try:
        result = reset_candidate_subtitles(session, candidate_id)
        session.commit()
        return result
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/subtitles/quality", response_model=SubtitleQualityRead)
def read_subtitle_quality(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return subtitle_quality_report(session, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/subtitles/auto-split", response_model=list[CandidateSubtitlePayload])
def auto_split_subtitles(candidate_id: int, session: Session = Depends(get_session)):
    try:
        result = auto_split_candidate_subtitles(session, candidate_id)
        session.commit()
        return result
    except ValueError as exc:
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
    except ValueError as exc:
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
    except ValueError as exc:
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
    except ValueError as exc:
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
    except ValueError as exc:
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
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
