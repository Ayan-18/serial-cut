from __future__ import annotations

from pathlib import Path

import pytest

from app.application.cache import cache_summary, clear_cache
from app.application.candidate_editor import EditableSubtitle, save_candidate_subtitles, subtitles_for_candidate
from app.application.importer import import_season
from app.infrastructure.config import Settings
from app.media.rendering import build_render_args
from app.models.entities import ClipCandidate, TranscriptSegment, WordTimestamp
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
