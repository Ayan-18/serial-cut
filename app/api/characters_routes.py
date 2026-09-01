from __future__ import annotations

from app.api._shared import *  # noqa: F403

router = APIRouter(prefix="/api")

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
    except ValueError as exc:
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
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/characters/{character_id}/photos/{photo_index}")
def character_photo(character_id: int, photo_index: int, session: Session = Depends(get_session)):
    character = session.get(Character, character_id)
    if character is None or photo_index < 0 or photo_index >= len(character.photos_json or []):
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    try:
        path = resolve_within(character.photos_json[photo_index], [get_settings().characters_dir])
    except PathOutsideAllowedRootsError as exc:
        raise HTTPException(status_code=404, detail="Фотография не найдена") from exc
    if not path.is_file():
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
    except ValueError as exc:
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
    except ValueError as exc:
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
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

