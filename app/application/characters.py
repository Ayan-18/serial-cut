from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.atomic import replace_atomically, temp_sibling
from app.infrastructure.config import Settings
from app.media.character_recognition import CharacterProfile, recognize_speaker_clusters
from app.media.voice_identity import (
    VoiceEmbedding,
    merge_voice_profile,
    recognize_voice_clusters,
    voice_profile_from_json,
    extract_voice_embedding,
)
from app.models.entities import Character, Episode, SpeakerIdentity, TranscriptSegment


_DATA_URL = re.compile(r"^data:image/(jpeg|png|webp);base64,(.+)$", re.IGNORECASE | re.DOTALL)
_EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
_MAX_PHOTO_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class CharacterRecognitionResult:
    identities: list[SpeakerIdentity]
    face_model: str
    voice_profiles_used: int


def add_character_photo(character: Character, data_url: str, characters_dir: Path) -> str:
    match = _DATA_URL.fullmatch(data_url.strip())
    if match is None:
        raise ValueError("Фото должно быть JPEG, PNG или WebP")
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Фото повреждено или имеет неверный формат") from exc
    if not content or len(content) > _MAX_PHOTO_BYTES:
        raise ValueError("Размер фотографии должен быть от 1 байта до 8 МБ")
    _validate_image(content)
    extension = _EXTENSIONS[match.group(1).lower()]
    final_path = (characters_dir / str(character.season_id) / f"{uuid4().hex}{extension}").resolve()
    root = characters_dir.resolve()
    if root not in final_path.parents:
        raise ValueError("Небезопасный путь фотографии")
    temp_path = temp_sibling(final_path)
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(content)
    replace_atomically(temp_path, final_path)
    character.photos_json = [*(character.photos_json or []), str(final_path)]
    return str(final_path)


def assign_speaker_identity(
    session: Session,
    episode_id: int,
    source_label: str,
    character_id: int,
    confidence: float | None = None,
    method: str = "manual",
) -> SpeakerIdentity:
    episode = session.get(Episode, episode_id)
    character = session.get(Character, character_id)
    if episode is None:
        raise ValueError("Серия не найдена")
    if character is None or character.season_id != episode.season_id:
        raise ValueError("Персонаж не относится к сезону этой серии")
    identity = session.scalar(
        select(SpeakerIdentity).where(
            SpeakerIdentity.episode_id == episode_id,
            SpeakerIdentity.source_label == source_label,
        )
    )
    if identity is None:
        identity = SpeakerIdentity(episode_id=episode_id, source_label=source_label, character_id=character_id)
        session.add(identity)
    identity.character_id = character_id
    identity.confidence = confidence
    identity.method = method
    session.flush()
    return identity


def recognize_episode_characters(
    session: Session,
    episode_id: int,
    settings: Settings,
) -> CharacterRecognitionResult:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError("Серия не найдена")
    characters = session.scalars(
        select(Character).where(Character.season_id == episode.season_id).order_by(Character.name)
    ).all()
    face_profiles = [
        CharacterProfile(item.id, item.name, [Path(path) for path in item.photos_json or []])
        for item in characters
        if item.photos_json
    ]
    voice_profiles = [
        profile
        for item in characters
        if (profile := voice_profile_from_json(item.id, item.name, item.voice_profile_json)) is not None
    ]
    if not face_profiles and not voice_profiles:
        raise ValueError("Сначала добавьте фотографии или обучите голос персонажа вручную")
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.start_time)
    ).all()
    ranges: dict[str, list[tuple[float, float]]] = {}
    for segment in segments:
        if segment.speaker_label and segment.speaker_label.startswith("Говорящий "):
            ranges.setdefault(segment.speaker_label, []).append((segment.start_time, segment.end_time))
    video_path = Path(episode.proxy_path or episode.file_path)
    audio_path = Path(episode.audio_path) if episode.audio_path else None
    session.commit()
    face_suggestions, face_model = recognize_speaker_clusters(
        video_path,
        ranges,
        face_profiles,
        settings.face_detector_model,
        settings.face_recognizer_model,
    )
    voice_suggestions = []
    voice_embeddings: dict[str, VoiceEmbedding] = {}
    if audio_path is not None and audio_path.exists():
        voice_suggestions, voice_embeddings = recognize_voice_clusters(
            audio_path, ranges, voice_profiles
        )
    face_by_label = {item.source_label: item for item in face_suggestions}
    voice_by_label = {item.source_label: item for item in voice_suggestions}
    identities: list[SpeakerIdentity] = []
    for source_label in sorted(set(face_by_label) | set(voice_by_label)):
        face = face_by_label.get(source_label)
        voice = voice_by_label.get(source_label)
        if face is not None and voice is not None and face.character_id != voice.character_id:
            continue
        if face is not None and voice is not None:
            character_id = face.character_id
            confidence = round(face.confidence * 0.65 + voice.confidence * 0.35, 3)
            method = "face+lip+voice"
        elif face is not None:
            character_id = face.character_id
            confidence = face.confidence
            method = "face+lip"
        elif voice is not None:
            character_id = voice.character_id
            confidence = voice.confidence
            method = "voice"
        else:
            continue
        identity = assign_speaker_identity(
            session,
            episode_id,
            source_label,
            character_id,
            confidence=confidence,
            method=method,
        )
        identities.append(identity)
        embedding = voice_embeddings.get(source_label)
        character = session.get(Character, character_id)
        if embedding is not None and character is not None and (face is not None or confidence >= 0.88):
            character.voice_profile_json = merge_voice_profile(character.voice_profile_json, embedding)
    session.flush()
    return CharacterRecognitionResult(identities, face_model, len(voice_profiles))


def train_character_voice(
    session: Session,
    episode_id: int,
    source_label: str,
    character_id: int,
) -> int:
    episode = session.get(Episode, episode_id)
    character = session.get(Character, character_id)
    if episode is None or character is None or not episode.audio_path:
        return 0
    audio_path = Path(episode.audio_path)
    if not audio_path.exists():
        return 0
    ranges = [
        (item.start_time, item.end_time)
        for item in session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.episode_id == episode_id,
                TranscriptSegment.speaker_label == source_label,
            )
            .order_by(TranscriptSegment.start_time)
        ).all()
    ]
    session.commit()
    embedding = extract_voice_embedding(audio_path, ranges)
    if embedding is None:
        return 0
    character = session.get(Character, character_id)
    if character is None:
        return 0
    character.voice_profile_json = merge_voice_profile(character.voice_profile_json, embedding)
    session.flush()
    return embedding.sample_count


def merge_characters(session: Session, source_character_id: int, target_character_id: int) -> Character:
    if source_character_id == target_character_id:
        raise ValueError("Выберите двух разных персонажей")
    source = session.get(Character, source_character_id)
    target = session.get(Character, target_character_id)
    if source is None or target is None:
        raise ValueError("Персонаж не найден")
    if source.season_id != target.season_id:
        raise ValueError("Можно объединять только персонажей одного сезона")

    target.description = _merge_text(target.description, source.description)
    target.aliases_json = _unique([*(target.aliases_json or []), source.name, *(source.aliases_json or [])])
    target.photos_json = _unique([*(target.photos_json or []), *(source.photos_json or [])])
    if not target.voice_profile_json and source.voice_profile_json:
        target.voice_profile_json = source.voice_profile_json
    identities = session.scalars(
        select(SpeakerIdentity).where(SpeakerIdentity.character_id == source_character_id)
    ).all()
    for identity in identities:
        identity.character_id = target_character_id
        identity.method = "manual" if identity.method == "manual" else f"{identity.method}+merged"
    session.delete(source)
    session.flush()
    return target


def speaker_name_map(session: Session, episode_id: int) -> dict[str, str]:
    rows = session.execute(
        select(SpeakerIdentity.source_label, Character.name)
        .join(Character, Character.id == SpeakerIdentity.character_id)
        .where(SpeakerIdentity.episode_id == episode_id)
    ).all()
    return {source: name for source, name in rows}


def _validate_image(content: bytes) -> None:
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 80 or image.shape[1] < 80:
        raise ValueError("Не удалось прочитать фотографию или она слишком маленькая")


def _merge_text(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right or right in left:
        return left
    return f"{left}\n{right}"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
