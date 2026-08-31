from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pytest

from app.application.cache import cache_summary, clear_cache
from app.application.candidate_editor import (
    EditableSubtitle,
    save_candidate_subtitles,
    subtitle_cues_for_render,
    subtitles_for_candidate,
)
from app.application.characters import add_character_photo, assign_speaker_identity
from app.application.importer import import_season
from app.application.processing_guard import ProcessingBusyError, processing_guard
from app.infrastructure.config import Settings
from app.infrastructure.database import make_engine
from app.media.rendering import build_render_args
from app.media.character_recognition import FaceObservation, face_signature, select_lip_active_face
from app.media.voice_identity import VoiceEmbedding, merge_voice_profile, voice_signature
from app.models.entities import Character, ClipCandidate, Episode, TranscriptSegment, WordTimestamp
from app.workers.queue import enqueue_candidate_render
from app.workers.runner import run_next_job


def _candidate(session, tmp_path: Path) -> ClipCandidate:
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    (season_dir / "episode.mkv").write_bytes(b"video")
    episode_id = import_season(session, season_dir).episode_ids[0]
    candidate = ClipCandidate(
        episode_id=episode_id,
        start_time=10,
        end_time=20,
        title="Момент",
        description="Описание",
        moment_type="другое",
        score=85,
        scores_json={},
        rationale="Понятен отдельно",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()
    return candidate


def test_candidate_subtitles_can_be_generated_edited_and_validated(session, tmp_path: Path):
    candidate = _candidate(session, tmp_path)
    segment = TranscriptSegment(
        episode_id=candidate.episode_id,
        start_time=10,
        end_time=14,
        text="Первая реплика.",
        speaker_label="Говорящий 1",
    )
    session.add(segment)
    session.flush()
    session.add_all(
        [
            WordTimestamp(segment_id=segment.id, start_time=10.1, end_time=10.5, word="Первая"),
            WordTimestamp(segment_id=segment.id, start_time=10.6, end_time=11.1, word="реплика."),
        ]
    )
    session.flush()

    generated = subtitles_for_candidate(session, candidate.id)
    assert generated
    assert generated[0].speaker_label == "Говорящий 1"

    saved = save_candidate_subtitles(
        session,
        candidate.id,
        [EditableSubtitle(None, 0.2, 1.5, "Исправленный текст", "Говорящий 1")],
    )
    assert saved[0].text == "Исправленный текст"

    with pytest.raises(ValueError, match="внутри границ"):
        save_candidate_subtitles(session, candidate.id, [EditableSubtitle(None, 9, 11, "Поздно")])


def test_character_identity_resolves_speaker_and_can_render_name(session, tmp_path: Path):
    candidate = _candidate(session, tmp_path)
    segment = TranscriptSegment(
        episode_id=candidate.episode_id,
        start_time=10,
        end_time=14,
        text="Реплика персонажа.",
        speaker_label="Говорящий 1",
    )
    session.add(segment)
    session.flush()
    session.add(WordTimestamp(segment_id=segment.id, start_time=10.1, end_time=11, word="Реплика."))
    episode = session.get(Episode, candidate.episode_id)
    assert episode is not None
    character = Character(season_id=episode.season_id, name="Мария")
    session.add(character)
    session.flush()

    assign_speaker_identity(session, candidate.episode_id, "Говорящий 1", character.id)

    generated = subtitles_for_candidate(session, candidate.id)
    rendered = subtitle_cues_for_render(session, candidate, show_speaker_names=True)
    assert generated[0].speaker_label == "Мария"
    assert "Мария:" in rendered[0].text


def test_character_photo_is_validated_and_stored_in_local_character_directory(session, tmp_path: Path):
    import cv2

    candidate = _candidate(session, tmp_path)
    episode = session.get(Episode, candidate.episode_id)
    assert episode is not None
    character = Character(season_id=episode.season_id, name="Антон")
    session.add(character)
    session.flush()
    image = np.full((100, 100, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    data_url = "data:image/png;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")

    path = Path(add_character_photo(character, data_url, tmp_path / "characters"))
    second_path = Path(add_character_photo(character, data_url, tmp_path / "characters"))

    assert path.exists()
    assert (tmp_path / "characters").resolve() in path.parents
    assert second_path.exists()
    assert len(character.photos_json) == 2


def test_face_signature_is_deterministic_for_the_same_crop():
    image = np.arange(96 * 96, dtype=np.uint8).reshape(96, 96)

    first = face_signature(image)
    second = face_signature(image.copy())

    assert np.allclose(first, second)


def test_lip_motion_selects_the_face_whose_mouth_changed():
    still = np.full((120, 220, 3), 100, dtype=np.uint8)
    current = still.copy()
    quiet = FaceObservation(20, 20, 60, 80, 1.0, np.ones(4, dtype=np.float32))
    speaking = FaceObservation(130, 20, 60, 80, 1.0, np.ones(4, dtype=np.float32))
    current[72:82, 148:172] = 20

    selected, score = select_lip_active_face(
        current,
        [quiet, speaking],
        still,
        [quiet, speaking],
    )

    assert selected is speaking
    assert score > 0


def test_local_voiceprint_is_deterministic_and_profiles_can_be_merged():
    sample_rate = 16_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    low_voice = np.sin(2 * np.pi * 170 * time).astype(np.float32)
    high_voice = np.sin(2 * np.pi * 510 * time).astype(np.float32)
    low_signature = voice_signature(low_voice, sample_rate)

    assert np.allclose(low_signature, voice_signature(low_voice.copy(), sample_rate))
    assert float(np.dot(low_signature, voice_signature(high_voice, sample_rate))) < 0.8

    profile = merge_voice_profile(None, VoiceEmbedding(low_signature, 3, 4.5))
    updated = merge_voice_profile(profile, VoiceEmbedding(low_signature, 2, 3.0))
    assert updated["sample_count"] == 5
    assert updated["seconds"] == 7.5


def test_cache_cleanup_only_removes_files_inside_cache(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_file = cache_dir / "episode" / "proxy.mp4"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"1234")
    original = tmp_path / "original.mkv"
    original.write_bytes(b"video")

    assert cache_summary(cache_dir).bytes == 4
    with pytest.raises(ValueError, match="подтверждение"):
        clear_cache(cache_dir, confirmed=False)
    cleared = clear_cache(cache_dir, confirmed=True)

    assert cleared.files == 0
    assert original.read_bytes() == b"video"


def test_render_job_runs_through_persistent_queue(session, tmp_path: Path, monkeypatch):
    candidate = _candidate(session, tmp_path)
    job = enqueue_candidate_render(
        session,
        candidate.id,
        {"include_subtitles": True, "force_rerender": True},
    )
    called: dict[str, object] = {}

    def fake_render(session_arg, candidate_id, settings, **kwargs):
        called.update(candidate_id=candidate_id, include_subtitles=kwargs["include_subtitles"])

    monkeypatch.setattr("app.workers.runner.render_candidate", fake_render)
    result = run_next_job(session, Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"))

    assert result.job_id == job.id
    assert result.status == "completed"
    assert called == {"candidate_id": candidate.id, "include_subtitles": True}


def test_crop_offset_and_scale_are_in_ffmpeg_filter(tmp_path: Path):
    args = build_render_args(
        "ffmpeg",
        tmp_path / "input.mp4",
        tmp_path / "output.mp4",
        0,
        10,
        "auto-follow",
        None,
        False,
        crop_offset_x=1,
        crop_scale=1.25,
    )
    video_filter = args[args.index("-vf") + 1]

    assert "scale=-2:2400" in video_filter
    assert "1.0000" in video_filter


def test_face_tracking_keyframes_create_a_time_based_crop_expression(tmp_path: Path):
    args = build_render_args(
        "ffmpeg",
        tmp_path / "input.mp4",
        tmp_path / "output.mp4",
        0,
        10,
        "auto-follow",
        None,
        False,
        crop_keyframes=[{"time": 0, "offset": -0.5}, {"time": 5, "offset": 0.5}],
    )

    video_filter = args[args.index("-vf") + 1]
    assert "if(lt(t,5.000)" in video_filter
    assert "(t-0.000)/5.000" in video_filter


def test_processing_guard_rejects_a_second_heavy_operation():
    with processing_guard():
        with pytest.raises(ProcessingBusyError, match="тяжёлая задача"):
            with processing_guard():
                pass


def test_file_sqlite_uses_wal_and_busy_timeout(tmp_path: Path):
    database_path = tmp_path / "serialcuts.db"
    engine = make_engine(Settings(database_url=f"sqlite:///{database_path.as_posix()}"))
    try:
        with engine.connect() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
    finally:
        engine.dispose()

    assert journal_mode == "wal"
    assert busy_timeout == 30000
