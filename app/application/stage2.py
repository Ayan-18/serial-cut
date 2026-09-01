from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from sqlalchemy.orm import Session, selectinload

from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError, ProcessResult, run_process
from app.media.ffmpeg import create_proxy, extract_audio
from app.media.ffprobe import apply_probe_to_episode, probe_media
from app.media.scenes import PySceneDetectAdapter, SceneDetector, save_scenes
from app.media.tracks import select_russian_audio_track, select_russian_subtitle_track
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
    def __init__(
        self,
        runner: Callable[[list[str], int], ProcessResult] = run_process,
        progress_callback: Callable[[float, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.runner = runner
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check

    def prepare(self, session: Session, episode: Episode, settings: Settings) -> MediaPrepResult:
        _raise_if_cancelled(self.cancel_check)
        if episode.probe_json is None:
            _report(self.progress_callback, 0.04, "Чтение дорожек и параметров видео")
            summary = probe_media(
                settings.ffprobe_path,
                Path(episode.file_path),
                runner=self.runner,
            )
            apply_probe_to_episode(episode, summary)
            session.commit()

        audio_track = select_russian_audio_track(episode.tracks)
        subtitle_track = select_russian_subtitle_track(episode.tracks)
        episode.selected_audio_stream_index = audio_track.stream_index if audio_track else None
        episode.selected_subtitle_stream_index = subtitle_track.stream_index if subtitle_track else None

        base_dir = settings.cache_dir / "episodes" / episode.fingerprint
        audio_path = base_dir / "audio" / "ru_16khz_mono.wav"
        # v2 includes the selected Russian audio stream. The versioned name
        # prevents silently reusing older video-only proxies.
        proxy_path = base_dir / "proxy" / "proxy-audio-v2.mp4"
        if not audio_path.exists():
            _raise_if_cancelled(self.cancel_check)
            _report(self.progress_callback, 0.10, "Извлечение русской аудиодорожки")
            extract_audio(
                settings.ffmpeg_path,
                Path(episode.file_path),
                audio_path,
                episode.selected_audio_stream_index,
                runner=self.runner,
            )
        _report(self.progress_callback, 0.22, "Русская аудиодорожка готова")
        if not proxy_path.exists():
            _raise_if_cancelled(self.cancel_check)
            _report(self.progress_callback, 0.24, "Создание облегчённого proxy-видео")
            create_proxy(
                settings.ffmpeg_path,
                Path(episode.file_path),
                proxy_path,
                width=settings.proxy_width,
                crf=settings.proxy_crf,
                audio_stream_index=episode.selected_audio_stream_index,
                runner=self.runner,
            )
        _report(self.progress_callback, 0.38, "Proxy-видео готово")

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
    warnings: list[str] = field(default_factory=list)


def run_stage2_media_analysis(
    session: Session,
    episode_id: int,
    settings: Settings,
    media_preparer: MediaPreparer | None = None,
    transcriber: Transcriber | None = None,
    scene_detector: SceneDetector | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    runner: Callable[[list[str], int], ProcessResult] = run_process,
) -> Stage2Result:
    episode = session.get(Episode, episode_id, options=[selectinload(Episode.tracks)])
    if episode is None:
        raise ValueError(f"Episode {episode_id} not found")

    _report(progress_callback, 0.01, "Подготовка медиа")
    _raise_if_cancelled(cancel_check)
    media_preparer = media_preparer or FFmpegMediaPreparer(runner, progress_callback, cancel_check)
    prep = media_preparer.prepare(session, episode, settings)
    episode.stage = EpisodeStage.PROXIED.value
    session.commit()

    _raise_if_cancelled(cancel_check)
    _report(progress_callback, 0.40, "Запуск локального Whisper")
    transcriber = transcriber or _build_transcriber(
        settings,
        progress_callback=lambda value, message: _report(
            progress_callback, 0.40 + value * 0.32, message
        ),
        cancel_check=cancel_check,
    )
    transcript = transcriber.transcribe(prep.audio_path)
    _raise_if_cancelled(cancel_check)
    transcript_count = save_transcript(session, episode.id, transcript)
    episode.stage = EpisodeStage.TRANSCRIBED.value
    session.commit()
    warnings: list[str] = []
    try:
        _report(progress_callback, 0.74, "Группировка голосов")
        from app.media.speakers import assign_speaker_labels

        assign_speaker_labels(session, episode.id, prep.audio_path)
        session.commit()
    except Exception as exc:
        session.rollback()
        episode = session.get(Episode, episode_id, options=[selectinload(Episode.tracks)])
        warning = f"Speaker labeling skipped: {exc}"
        if episode is not None:
            _append_episode_warning(episode, "speaker_labeling", warning)
            session.commit()
        warnings.append(warning)

    _raise_if_cancelled(cancel_check)
    _report(progress_callback, 0.80, "Поиск границ сцен")
    scene_detector = scene_detector or PySceneDetectAdapter(
        progress_callback=lambda value, message: _report(
            progress_callback, 0.80 + value * 0.18, message
        ),
        cancel_check=cancel_check,
    )
    intervals = scene_detector.detect(prep.proxy_path)
    _raise_if_cancelled(cancel_check)
    scene_count = save_scenes(session, episode.id, intervals)
    episode.stage = EpisodeStage.SCENES_DETECTED.value
    session.commit()
    _report(progress_callback, 1.0, "Медиа-анализ завершён")

    return Stage2Result(
        episode_id=episode.id,
        stage=episode.stage,
        audio_path=episode.audio_path,
        proxy_path=episode.proxy_path,
        transcript_segments=transcript_count,
        scenes=scene_count,
        warnings=warnings,
    )


def _build_transcriber(
    settings: Settings,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Transcriber:
    if settings.asr_adapter == "stub":
        return StubTranscriber()
    return FasterWhisperTranscriber(
        model_name=settings.asr_model_name,
        compute_type=settings.asr_compute_type,
        fallback_compute_type=settings.asr_fallback_compute_type,
        device=settings.asr_device,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def _report(callback: Callable[[float, str], None] | None, value: float, message: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, value)), message)


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProcessCancelledError("Медиа-анализ остановлен пользователем")


def _append_episode_warning(episode: Episode, code: str, message: str) -> None:
    payload = dict(episode.probe_json or {})
    warnings = [dict(item) for item in payload.get("serialcuts_warnings") or []]
    warnings = [item for item in warnings if item.get("code") != code]
    warnings.append({"code": code, "message": message})
    payload["serialcuts_warnings"] = warnings[-20:]
    episode.probe_json = payload

