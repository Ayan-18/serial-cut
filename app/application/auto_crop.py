from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.review import save_candidate_edits
from app.infrastructure.config import Settings
from app.media.rendering import smooth_crop_keyframes
from app.models.entities import Character, ClipCandidate, Episode, SpeakerIdentity, TranscriptSegment


class FaceDetectionUnavailableError(RuntimeError):
    """No YuNet/SFace weights (and no Haar fallback) — nothing to track."""


@dataclass(frozen=True)
class AutoCropResult:
    candidate_id: int
    crop_offset_x: float
    faces_detected: int
    frames_sampled: int
    keyframes: list[dict]
    active_speaker_frames: int
    identified_speaker_frames: int
    lip_motion_frames: int
    face_model: str
    held_frames: int
    largest_face_frames: int
    average_confidence: float


def auto_crop_candidate(session: Session, candidate_id: int, settings: Settings) -> AutoCropResult:
    from app.media.character_recognition import CharacterProfile
    from app.media.face_tracking import SpeechRange, estimate_face_offset

    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError("Кандидат не найден")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise ValueError("Серия не найдена")

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
    profiles = [
        CharacterProfile(item.id, item.name, [Path(path) for path in item.photos_json or []])
        for item in session.scalars(
            select(Character).where(Character.season_id == episode.season_id)
        ).all()
        if item.photos_json
    ]
    session.commit()

    # Track on the source, not the low-res proxy: the proxy (~640px) loses small
    # or distant faces. estimate_face_offset downscales each read frame to 720px.
    source = Path(episode.file_path)
    if not source.exists():
        source = Path(episode.proxy_path or episode.file_path)
    result = estimate_face_offset(
        source,
        candidate.start_time,
        candidate.end_time,
        speech_ranges=speech_ranges,
        character_profiles=profiles,
        detector_model=settings.face_detector_model,
        recognizer_model=settings.face_recognizer_model,
        audio_path=Path(episode.audio_path) if episode.audio_path else None,
    )
    if not result.face_detection_available:
        raise FaceDetectionUnavailableError(
            "Поиск лиц недоступен: не установлены модели YuNet/SFace. "
            "Скачайте их в разделе «Локальные модели» или командой "
            "scripts\\install_identity_models.ps1, затем повторите."
        )

    save_candidate_edits(session, candidate.id, crop_mode="auto-follow", crop_offset_x=result.offset_x)
    candidate = session.get(ClipCandidate, candidate.id)
    assert candidate is not None
    candidate.crop_keyframes_json = smooth_crop_keyframes(result.keyframes)
    return AutoCropResult(
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
