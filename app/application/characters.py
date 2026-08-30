from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.atomic import replace_atomically, temp_sibling
from app.media.character_recognition import CharacterProfile, recognize_speaker_clusters
from app.models.entities import Character, Episode, SpeakerIdentity, TranscriptSegment


_DATA_URL = re.compile(r"^data:image/(jpeg|png|webp);base64,(.+)$", re.IGNORECASE | re.DOTALL)
_EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
_MAX_PHOTO_BYTES = 8 * 1024 * 1024


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


def recognize_episode_characters(session: Session, episode_id: int) -> list[SpeakerIdentity]:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError("Серия не найдена")
    characters = session.scalars(
        select(Character).where(Character.season_id == episode.season_id).order_by(Character.name)
    ).all()
    profiles = [
        CharacterProfile(item.id, item.name, [Path(path) for path in item.photos_json or []])
        for item in characters
        if item.photos_json
    ]
    if not profiles:
        raise ValueError("Сначала добавьте персонажей и их фотографии")
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.start_time)
    ).all()
    ranges: dict[str, list[tuple[float, float]]] = {}
    for segment in segments:
        if segment.speaker_label and segment.speaker_label.startswith("Говорящий "):
            ranges.setdefault(segment.speaker_label, []).append((segment.start_time, segment.end_time))
    suggestions = recognize_speaker_clusters(Path(episode.file_path), ranges, profiles)
    return [
        assign_speaker_identity(
            session,
            episode_id,
            item.source_label,
            item.character_id,
            confidence=item.confidence,
            method="face",
        )
        for item in suggestions
    ]


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
