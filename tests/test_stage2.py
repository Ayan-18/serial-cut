from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.application.importer import import_season
from app.application.stage2 import MediaPrepResult, run_stage2_media_analysis
from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.media.scenes import SceneInterval, StubSceneDetector, save_scenes
from app.media.transcription import StubTranscriber, TranscriptChunk, TranscriptResult, Word, save_transcript
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

    result = run_stage2_media_analysis(
        session,
        imported.episode_ids[0],
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        media_preparer=StubMediaPreparer(tmp_path / "cache" / "audio.wav", tmp_path / "cache" / "proxy.mp4"),
        transcriber=StubTranscriber(),
        scene_detector=StubSceneDetector(),
    )
    session.commit()

    episode = session.get(Episode, imported.episode_ids[0])
    assert result.stage == EpisodeStage.SCENES_DETECTED.value
    assert episode.stage == EpisodeStage.SCENES_DETECTED.value
    assert Path(episode.audio_path).exists()
    assert Path(episode.proxy_path).exists()
    assert session.scalar(select(TranscriptSegment).where(TranscriptSegment.episode_id == episode.id)) is not None
    assert session.scalar(select(Scene).where(Scene.episode_id == episode.id)) is not None

