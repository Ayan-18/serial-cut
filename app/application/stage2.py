from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy.orm import Session, selectinload

from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.media.ffmpeg import create_proxy, extract_audio
from app.media.ffprobe import apply_probe_to_episode, probe_media
from app.media.scenes import PySceneDetectAdapter, SceneDetector, save_scenes
from app.media.tracks import select_russian_audio_track, select_russian_subtitle_track
from app.media.speakers import assign_speaker_labels
from app.media.transcription import (
    FasterWhisperTranscriber,
    StubTranscriber,
    Transcriber,
    save_transcript,
)
from app.models.entities import Episode


@dataclass(frozen=True)
class MediaPrepResult:
    audio_path: Path
    proxy_path: Path
    audio_stream_index: int | None
    subtitle_stream_index: int | None


class MediaPreparer(Protocol):
    def prepare(self, session: Session, episode: Episode, settings: Settings) -> MediaPrepResult:
        ...


class FFmpegMediaPreparer:
    def prepare(self, session: Session, episode: Episode, settings: Settings) -> MediaPrepResult:
        if episode.probe_json is None:
            summary = probe_media(settings.ffprobe_path, Path(episode.file_path))
            apply_probe_to_episode(episode, summary)
            session.commit()

        audio_track = select_russian_audio_track(episode.tracks)
        subtitle_track = select_russian_subtitle_track(episode.tracks)
        episode.selected_audio_stream_index = audio_track.stream_index if audio_track else None
        episode.selected_subtitle_stream_index = subtitle_track.stream_index if subtitle_track else None

        base_dir = settings.cache_dir / "episodes" / episode.fingerprint
        audio_path = base_dir / "audio" / "ru_16khz_mono.wav"
        proxy_path = base_dir / "proxy" / "proxy.mp4"
        if not audio_path.exists():
            extract_audio(settings.ffmpeg_path, Path(episode.file_path), audio_path, episode.selected_audio_stream_index)
        if not proxy_path.exists():
            create_proxy(
                settings.ffmpeg_path,
                Path(episode.file_path),
                proxy_path,
                width=settings.proxy_width,
                crf=settings.proxy_crf,
            )

        episode.audio_path = str(audio_path)
        episode.proxy_path = str(proxy_path)
        episode.stage = EpisodeStage.PROXIED.value
        return MediaPrepResult(
            audio_path=audio_path,
            proxy_path=proxy_path,
            audio_stream_index=episode.selected_audio_stream_index,
            subtitle_stream_index=episode.selected_subtitle_stream_index,
        )


@dataclass(frozen=True)
class Stage2Result:
    episode_id: int
    stage: str
    audio_path: str | None
    proxy_path: str | None
    transcript_segments: int
    scenes: int


def run_stage2_media_analysis(
    session: Session,
    episode_id: int,
    settings: Settings,
    media_preparer: MediaPreparer | None = None,
    transcriber: Transcriber | None = None,
    scene_detector: SceneDetector | None = None,
) -> Stage2Result:
    episode = session.get(Episode, episode_id, options=[selectinload(Episode.tracks)])
    if episode is None:
        raise ValueError(f"Episode {episode_id} not found")

    media_preparer = media_preparer or FFmpegMediaPreparer()
    prep = media_preparer.prepare(session, episode, settings)
    episode.stage = EpisodeStage.PROXIED.value
    session.commit()

    transcriber = transcriber or _build_transcriber(settings)
    transcript = transcriber.transcribe(prep.audio_path)
    transcript_count = save_transcript(session, episode.id, transcript)
    episode.stage = EpisodeStage.TRANSCRIBED.value
    session.commit()
    try:
        assign_speaker_labels(session, episode.id, prep.audio_path)
        session.commit()
    except RuntimeError:
        session.rollback()

    scene_detector = scene_detector or PySceneDetectAdapter()
    intervals = scene_detector.detect(prep.proxy_path)
    scene_count = save_scenes(session, episode.id, intervals)
    episode.stage = EpisodeStage.SCENES_DETECTED.value
    session.commit()

    return Stage2Result(
        episode_id=episode.id,
        stage=episode.stage,
        audio_path=episode.audio_path,
        proxy_path=episode.proxy_path,
        transcript_segments=transcript_count,
        scenes=scene_count,
    )


def _build_transcriber(settings: Settings) -> Transcriber:
    if settings.asr_adapter == "stub":
        return StubTranscriber()
    return FasterWhisperTranscriber(
        model_name=settings.asr_model_name,
        compute_type=settings.asr_compute_type,
        fallback_compute_type=settings.asr_fallback_compute_type,
        device=settings.asr_device,
    )

