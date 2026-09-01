from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest
from sqlalchemy import select

from app.application.importer import import_season
from app.application.stage2 import MediaPrepResult, run_stage2_media_analysis
from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError
from app.media.scenes import SceneInterval, StubSceneDetector, save_scenes
from app.media.transcription import (
    FasterWhisperTranscriber,
    StubTranscriber,
    TranscriptChunk,
    TranscriptResult,
    Word,
    save_transcript,
)
from app.models.entities import Episode, Scene, TranscriptSegment, WordTimestamp


class StubMediaPreparer:
    def __init__(self, audio_path: Path, proxy_path: Path) -> None:
        self.audio_path = audio_path
        self.proxy_path = proxy_path

    def prepare(self, session, episode: Episode, settings: Settings) -> MediaPrepResult:
        self.audio_path.parent.mkdir(parents=True, exist_ok=True)
        self.proxy_path.parent.mkdir(parents=True, exist_ok=True)
        self.audio_path.write_bytes(b"stub-audio")
        self.proxy_path.write_bytes(b"stub-proxy")
        episode.audio_path = str(self.audio_path)
        episode.proxy_path = str(self.proxy_path)
        episode.selected_audio_stream_index = 1
        episode.selected_subtitle_stream_index = None
        return MediaPrepResult(self.audio_path, self.proxy_path, 1, None)


def test_save_transcript_replaces_previous_segments(session, tmp_path: Path):
    result = TranscriptResult(
        language="ru",
        segments=[
            TranscriptChunk(0.0, 1.0, "Привет", [Word(0.0, 0.5, "Привет")]),
        ],
    )
    save_transcript(session, 7, result)
    save_transcript(session, 7, result)
    session.commit()

    assert len(session.scalars(select(TranscriptSegment)).all()) == 1
    assert len(session.scalars(select(WordTimestamp)).all()) == 1


def test_save_scenes_replaces_previous_intervals(session):
    save_scenes(session, 7, [SceneInterval(0.0, 1.0)])
    save_scenes(session, 7, [SceneInterval(1.0, 2.0), SceneInterval(2.0, 3.0)])
    session.commit()

    scenes = session.scalars(select(Scene).order_by(Scene.start_time)).all()
    assert len(scenes) == 2
    assert scenes[0].start_time == 1.0


def test_stage2_smoke_with_stub_models(session, tmp_path: Path):
    season = tmp_path / "Сезон 2"
    season.mkdir()
    (season / "Серия 01.mkv").write_bytes(b"synthetic-video")
    imported = import_season(session, season)
    session.commit()

    class TransactionCheckingTranscriber:
        transaction_was_open = True

        def transcribe(self, audio_path: Path):
            self.transaction_was_open = session.in_transaction()
            return StubTranscriber().transcribe(audio_path)

    transcriber = TransactionCheckingTranscriber()
    result = run_stage2_media_analysis(
        session,
        imported.episode_ids[0],
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        media_preparer=StubMediaPreparer(tmp_path / "cache" / "audio.wav", tmp_path / "cache" / "proxy.mp4"),
        transcriber=transcriber,
        scene_detector=StubSceneDetector(),
    )
    session.commit()

    episode = session.get(Episode, imported.episode_ids[0])
    assert result.stage == EpisodeStage.SCENES_DETECTED.value
    assert episode.stage == EpisodeStage.SCENES_DETECTED.value
    assert Path(episode.audio_path).exists()
    assert Path(episode.proxy_path).exists()
    assert transcriber.transaction_was_open is False
    assert session.scalar(select(TranscriptSegment).where(TranscriptSegment.episode_id == episode.id)) is not None
    assert session.scalar(select(Scene).where(Scene.episode_id == episode.id)) is not None


def test_stage2_records_speaker_labeling_warning(session, tmp_path: Path, monkeypatch):
    season = tmp_path / "Сезон 2"
    season.mkdir()
    (season / "Серия 01.mkv").write_bytes(b"synthetic-video")
    imported = import_season(session, season)
    session.commit()

    def broken_speaker_labels(*_args, **_kwargs):
        raise RuntimeError("speaker model unavailable")

    speakers_module = types.ModuleType("app.media.speakers")
    speakers_module.assign_speaker_labels = broken_speaker_labels
    monkeypatch.setitem(sys.modules, "app.media.speakers", speakers_module)
    result = run_stage2_media_analysis(
        session,
        imported.episode_ids[0],
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        media_preparer=StubMediaPreparer(tmp_path / "cache" / "audio.wav", tmp_path / "cache" / "proxy.mp4"),
        transcriber=StubTranscriber(),
        scene_detector=StubSceneDetector(),
    )

    episode = session.get(Episode, imported.episode_ids[0])
    warnings = (episode.probe_json or {}).get("serialcuts_warnings")
    assert result.warnings and "speaker model unavailable" in result.warnings[0]
    assert warnings and warnings[0]["code"] == "speaker_labeling"


def test_faster_whisper_auto_device_falls_back_to_cpu(monkeypatch, tmp_path: Path):
    transcriber = FasterWhisperTranscriber("small", "int8_float16", "int8", device="auto")
    calls: list[tuple[str, str]] = []
    expected = TranscriptResult(language="ru", segments=[])

    def fake_transcribe(device: str, compute_type: str, audio_path: Path):
        calls.append((device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA runtime is unavailable")
        return expected

    monkeypatch.setattr(transcriber, "_transcribe_with", fake_transcribe)

    assert transcriber.transcribe(tmp_path / "audio.wav") is expected
    assert calls == [("cuda", "int8_float16"), ("cuda", "int8"), ("cpu", "int8")]


def test_faster_whisper_cancellation_does_not_restart_on_fallback_device(monkeypatch, tmp_path: Path):
    transcriber = FasterWhisperTranscriber("small", "int8_float16", "int8", device="auto")
    calls: list[tuple[str, str]] = []

    def cancelled(device: str, compute_type: str, _audio_path: Path):
        calls.append((device, compute_type))
        raise ProcessCancelledError("остановлено")

    monkeypatch.setattr(transcriber, "_transcribe_with", cancelled)

    with pytest.raises(ProcessCancelledError, match="остановлено"):
        transcriber.transcribe(tmp_path / "audio.wav")
    assert calls == [("cuda", "int8_float16")]

