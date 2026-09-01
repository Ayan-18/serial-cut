from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.infrastructure.config import Settings
from app.media.thumbnails import Keyframe, extract_keyframes
from app.models.entities import ClipCandidate, Episode

DEFAULT_KEYFRAME_COUNT = 8


@dataclass(frozen=True)
class KeyframeInfo:
    index: int
    time: float
    url: str


@dataclass(frozen=True)
class KeyframeStrip:
    candidate_id: int
    edit_revision: int
    start_time: float
    end_time: float
    frames: list[KeyframeInfo]


def _candidate_and_episode(session: Session, candidate_id: int) -> tuple[ClipCandidate, Episode]:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    episode = session.get(Episode, candidate.episode_id)
    if episode is None:
        raise ValueError(f"Episode {candidate.episode_id} not found")
    return candidate, episode


def _output_dir(settings: Settings, episode: Episode, candidate: ClipCandidate) -> Path:
    return (
        settings.cache_dir
        / "keyframes"
        / episode.fingerprint
        / f"c{candidate.id}-r{candidate.edit_revision}"
    )


def _source_path(episode: Episode) -> Path:
    source = episode.proxy_path or episode.file_path
    return Path(source)


def build_candidate_keyframes(
    session: Session,
    candidate_id: int,
    settings: Settings,
    count: int = DEFAULT_KEYFRAME_COUNT,
) -> KeyframeStrip:
    candidate, episode = _candidate_and_episode(session, candidate_id)
    source = _source_path(episode)
    if not source.exists():
        raise ValueError("Нет proxy или исходного файла для раскадровки")
    frames: list[Keyframe] = extract_keyframes(
        settings.ffmpeg_path,
        source,
        _output_dir(settings, episode, candidate),
        candidate.start_time,
        candidate.end_time,
        count,
    )
    return KeyframeStrip(
        candidate_id=candidate.id,
        edit_revision=candidate.edit_revision,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        frames=[
            KeyframeInfo(
                index=frame.index,
                time=frame.time,
                url=f"/api/candidates/{candidate.id}/keyframes/{frame.index}",
            )
            for frame in frames
        ],
    )


def candidate_keyframe_file(
    session: Session,
    candidate_id: int,
    settings: Settings,
    index: int,
) -> Path:
    candidate, episode = _candidate_and_episode(session, candidate_id)
    path = _output_dir(settings, episode, candidate) / f"frame-{index + 1:02d}.jpg"
    if not path.is_file():
        raise ValueError("Кадр не найден — постройте раскадровку заново")
    return path
