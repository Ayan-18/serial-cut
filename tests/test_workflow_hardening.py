from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

from app.application.global_search import search_season
from app.application.importer import import_season
from app.application.publishing import (
    PublishingPlanRequest,
    create_publishing_package,
    create_publishing_plan,
    update_publishing_plan,
)
from app.application.review import save_candidate_edits
from app.application.stage3 import run_stage3_candidate_analysis
from app.application.narration import build_narration_timeline_args
from app.application.story_arc_render import build_crossfade_args, build_narration_mix_args
from app.application.story_arcs import (
    StoryArcPlanRequest,
    create_story_arc_plan,
    rebuild_story_arc_plan,
    remove_story_arc_segment,
)
from app.application.video_scripts import VideoScriptRequest, create_video_script
from app.analysis.local_text import generate_local_text
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError
from app.media.rendering import RENDER_PRESETS
from app.media.voice_identity import VoiceEmbedding, merge_voice_profile, voice_profile_from_json
from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    Episode,
    Export,
    Job,
    Scene,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    TranscriptSegment,
    WordTimestamp,
)
from app.workers.queue import enqueue_candidate_render
from app.workers.runner import estimate_eta_seconds, run_next_job


def _import_episode(session, tmp_path: Path) -> tuple[int, Path]:
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    source = season_dir / "s01e01.mkv"
    source.write_bytes(b"video")
    episode_id = import_season(session, season_dir).episode_ids[0]
    episode = session.get(Episode, episode_id)
    episode.duration_seconds = 120
    return episode_id, source


def _candidate(episode_id: int, *, title: str = "Герой раскрывает тайну") -> ClipCandidate:
    return ClipCandidate(
        episode_id=episode_id,
        start_time=10,
        end_time=40,
        title=title,
        description="Герой узнаёт скрытую правду и принимает решение.",
        moment_type="откровение",
        score=88,
        scores_json={"payoff": 88},
        rationale="Понятная самостоятельная сцена",
        problems_json=[],
        status="rendered",
    )


def test_candidate_edit_snaps_dialogue_and_invalidates_derived_outputs(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    candidate = _candidate(episode_id)
    session.add(candidate)
    session.flush()
    session.add(TranscriptSegment(episode_id=episode_id, start_time=5, end_time=15, text="Полная реплика"))
    session.add(CandidateSubtitle(candidate_id=candidate.id, start_time=0, end_time=2, text="Старые субтитры"))
    clip_export = Export(candidate_id=candidate.id, output_path=str(tmp_path / "old.mp4"), status="completed")
    arc = StoryArc(season_id=session.get(Episode, episode_id).season_id, title="Арка", prompt="", plan_json={})
    session.add_all([clip_export, arc])
    session.flush()
    segment = StoryArcSegment(
        story_arc_id=arc.id, episode_id=episode_id, candidate_id=candidate.id,
        sort_order=1, start_time=10, end_time=40, title="Арка", note="",
    )
    arc_export = StoryArcExport(story_arc_id=arc.id, output_path=str(tmp_path / "arc.mp4"), status="completed")
    session.add_all([segment, arc_export])
    session.flush()

    save_candidate_edits(session, candidate.id, adjusted_start_time=9, adjusted_end_time=42)
    session.flush()

    assert candidate.start_time == 5
    assert candidate.end_time == 42
    assert candidate.edit_revision == 1
    assert candidate.status == "approved"
    assert session.scalar(select(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate.id)) is None
    assert clip_export.status == "stale"
    assert (segment.start_time, segment.end_time, segment.candidate_revision) == (5, 42, 1)
    assert arc.status == "draft" and arc.edit_revision == 1
    assert arc_export.status == "stale"


def test_story_arc_rebuild_preserves_manually_edited_segment(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    first = _candidate(episode_id, title="Первый поворот")
    second = _candidate(episode_id, title="Второй поворот")
    second.start_time, second.end_time, second.score = 50, 80, 84
    first.status = second.status = "approved"
    session.add_all([first, second])
    session.flush()
    arc = create_story_arc_plan(session, StoryArcPlanRequest(season_id=session.get(Episode, episode_id).season_id, max_segments=2))
    kept = arc.segments[0]
    kept.start_time = 12
    kept.end_time = 39
    kept.manually_edited = True
    kept.title = "Ручная версия"
    session.flush()

    rebuilt = rebuild_story_arc_plan(session, arc.id, Settings(llm_adapter="stub"))

    preserved = next(item for item in rebuilt.segments if item.id == kept.id)
    assert (preserved.start_time, preserved.end_time, preserved.title) == (12, 39, "Ручная версия")
    assert preserved.manually_edited is True


def test_crossfade_uses_video_and_audio_transitions(tmp_path):
    args = build_crossfade_args(
        "ffmpeg",
        [tmp_path / "one.mp4", tmp_path / "two.mp4", tmp_path / "three.mp4"],
        [10, 12, 8],
        tmp_path / "out.mp4",
    )
    filters = args[args.index("-filter_complex") + 1]
    assert filters.count("xfade=") == 2
    assert filters.count("acrossfade=") == 2
    assert "offset=9.750" in filters


def test_crossfade_respects_nvenc_and_render_preset(tmp_path):
    args = build_crossfade_args(
        "ffmpeg",
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        [10, 12],
        tmp_path / "out.mp4",
        preset=RENDER_PRESETS["instagram_reels"],
        use_nvenc=True,
    )

    assert args[args.index("-c:v") + 1] == "h264_nvenc"
    assert args[args.index("-b:v") + 1] == "10M"
    assert args[args.index("-b:a") + 1] == "192k"


def test_narration_is_scheduled_and_ducks_only_while_voice_is_present(tmp_path):
    timeline = build_narration_timeline_args(
        "ffmpeg",
        [tmp_path / "one.wav", tmp_path / "two.wav"],
        [{"start_time": 0.5}, {"start_time": 8.0}],
        [2.0, 2.5],
        15.0,
        tmp_path / "timeline.wav",
    )
    filters = timeline[timeline.index("-filter_complex") + 1]
    assert "adelay=500:all=1" in filters
    assert "adelay=8000:all=1" in filters
    assert "atrim=duration=15.000" in filters

    mix = build_narration_mix_args(
        "ffmpeg", tmp_path / "video.mp4", tmp_path / "timeline.wav", 15.0, tmp_path / "out.mp4"
    )
    mix_filters = mix[mix.index("-filter_complex") + 1]
    assert "sidechaincompress=" in mix_filters
    assert "amix=inputs=2:duration=first" in mix_filters

    with pytest.raises(ValueError, match="не помещается"):
        build_narration_timeline_args(
            "ffmpeg", [tmp_path / "long.wav"], [{"start_time": 0.0}], [20.0], 5.0, tmp_path / "bad.wav"
        )


def test_semantic_search_matches_russian_synonyms(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    session.add(_candidate(episode_id, title="Скрытый секрет семьи"))
    session.flush()

    results = search_season(session, session.get(Episode, episode_id).season_id, "раскрытие правды")

    assert results and results[0].candidate_id is not None


def test_search_fts_index_tracks_candidate_updates(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    candidate = _candidate(episode_id, title="Старое название")
    session.add(candidate)
    session.flush()
    season_id = session.get(Episode, episode_id).season_id
    assert search_season(session, season_id, "старое название")

    candidate.title = "Синяя комета возвращается"
    session.flush()

    updated = search_season(session, season_id, "синяя комета")
    assert updated and updated[0].candidate_id == candidate.id


def test_story_arc_rebuild_keeps_original_limits_after_segment_removal(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    candidates = []
    titles = ["Находка письма", "Ночная погоня", "Признание врага", "Спасение города"]
    descriptions = [
        "Письмо объясняет давнюю загадку.",
        "Машины преследуют героя ночью.",
        "Враг признаётся в подмене документов.",
        "Команда останавливает аварию и спасает жителей.",
    ]
    for index, title in enumerate(titles):
        candidate = _candidate(episode_id, title=title)
        candidate.description = descriptions[index]
        candidate.start_time = index * 25
        candidate.end_time = index * 25 + 20
        candidate.score = 90 - index
        candidates.append(candidate)
    session.add_all(candidates)
    session.flush()
    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(
            season_id=session.get(Episode, episode_id).season_id,
            max_segments=3,
            max_duration_seconds=65,
        ),
    )
    removed_id = arc.segments[-1].id
    remove_story_arc_segment(session, arc.id, removed_id)

    rebuilt = rebuild_story_arc_plan(session, arc.id, Settings(llm_adapter="stub"))

    assert rebuilt.plan_json["constraints"] == {"max_segments": 3, "max_duration_seconds": 65}
    # The selector intentionally caps early plans at two clips per episode;
    # after removing one it can still restore the original plan capacity.
    assert len(rebuilt.segments) == 2
    assert rebuilt.total_duration_seconds <= 65


def test_eta_uses_real_job_durations_and_running_progress(session):
    now = datetime.now(timezone.utc)
    session.add_all(
        [
            Job(kind="analyze_episode", status="completed", started_at=now - timedelta(seconds=100), finished_at=now),
            Job(kind="render_clip", status="completed", started_at=now - timedelta(seconds=40), finished_at=now),
            Job(kind="analyze_episode", status="running", progress=0.25, started_at=now),
            Job(kind="render_clip", status="queued", progress=0),
        ]
    )
    session.flush()

    assert estimate_eta_seconds(session) == pytest.approx(115.0)


def test_publishing_package_is_local_validated_manifest(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    candidate = _candidate(episode_id)
    candidate.status = "approved"
    session.add(candidate)
    session.flush()
    arc = create_story_arc_plan(session, StoryArcPlanRequest(season_id=session.get(Episode, episode_id).season_id))
    video = tmp_path / "story.mp4"
    video.write_bytes(b"video")
    export = StoryArcExport(story_arc_id=arc.id, output_path=str(video), status="completed")
    session.add(export)
    session.flush()
    plan = create_publishing_plan(
        session,
        PublishingPlanRequest(
            season_id=arc.season_id,
            story_arc_id=arc.id,
            story_arc_export_id=export.id,
            platform="youtube_shorts",
        ),
    )

    manifest = create_publishing_package(session, plan.id, tmp_path / "out")
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["video_path"] == str(video)
    assert payload["privacy"].startswith("Upload is manual")
    assert plan.status == "ready"
    with pytest.raises(ValueError, match="Заголовок длиннее"):
        update_publishing_plan(session, plan.id, title="x" * 101)


def test_stage3_keeps_story_arc_snapshot_when_candidates_are_regenerated(session, tmp_path):
    episode_id, _ = _import_episode(session, tmp_path)
    transcript = TranscriptSegment(episode_id=episode_id, start_time=0, end_time=39, text="Герой узнаёт правду.")
    session.add(transcript)
    session.flush()
    session.add(WordTimestamp(segment_id=transcript.id, start_time=1, end_time=2, word="Герой"))
    session.add(Scene(episode_id=episode_id, start_time=0, end_time=40))
    settings = Settings(
        asr_adapter="stub",
        llm_adapter="stub",
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "out",
    )
    run_stage3_candidate_analysis(session, episode_id, settings)
    old_candidate = session.scalar(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
    old_video = settings.output_dir / "old.mp4"
    old_metadata = settings.output_dir / "old.json"
    old_video.parent.mkdir(parents=True)
    old_video.write_bytes(b"derived")
    old_metadata.write_text("{}", encoding="utf-8")
    session.add(
        Export(
            candidate_id=old_candidate.id,
            output_path=str(old_video),
            metadata_path=str(old_metadata),
        )
    )
    session.flush()
    arc = create_story_arc_plan(session, StoryArcPlanRequest(season_id=session.get(Episode, episode_id).season_id))
    old_segment_id = arc.segments[0].id

    run_stage3_candidate_analysis(session, episode_id, settings)

    snapshot = session.get(StoryArcSegment, old_segment_id)
    assert snapshot is not None and snapshot.candidate_id is None
    assert snapshot.manually_edited is True
    assert "оставлен снимок границ" in snapshot.note
    assert session.get(ClipCandidate, old_candidate.id) is None
    assert not old_video.exists() and not old_metadata.exists()


def test_worker_marks_cancelled_render_as_paused(session, tmp_path, monkeypatch):
    episode_id, _ = _import_episode(session, tmp_path)
    candidate = _candidate(episode_id)
    session.add(candidate)
    session.flush()
    job = enqueue_candidate_render(session, candidate.id, {})
    session.commit()

    def cancelled(*_args, **_kwargs):
        raise ProcessCancelledError("Операция остановлена пользователем")

    monkeypatch.setattr("app.workers.runner.render_candidate", cancelled)
    result = run_next_job(session, Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"))

    assert result.status == "paused"
    assert job.status == "paused"
    assert job.stages[0].status == "paused"
    assert job.progress_message == "Задача остановлена"
    assert job.started_at is not None and job.finished_at is not None


def test_local_llm_can_reorder_story_arc_and_write_script(session, tmp_path, monkeypatch):
    season_dir = tmp_path / "llm-season"
    season_dir.mkdir()
    (season_dir / "s01e01.mkv").write_bytes(b"one")
    (season_dir / "s01e02.mkv").write_bytes(b"two")
    imported = import_season(session, season_dir)
    first = _candidate(imported.episode_ids[0], title="Причина конфликта")
    first.description = "Герой впервые находит письмо и ещё не знает последствий."
    second = _candidate(imported.episode_ids[1], title="Развязка конфликта")
    second.description = "Герой предъявляет письмо и получает окончательный ответ."
    session.add_all([first, second])
    session.flush()
    monkeypatch.setattr(
        "app.application.story_arcs.generate_local_text",
        lambda *_args, **_kwargs: json.dumps({"candidate_ids": [second.id, first.id]}),
    )
    settings = Settings(llm_adapter="llama-cpp-http")

    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(season_id=imported.season.id, max_segments=2),
        settings,
    )

    assert [item.candidate_id for item in arc.segments] == [second.id, first.id]
    monkeypatch.setattr("app.application.video_scripts.generate_local_text", lambda *_args, **_kwargs: "ГОТОВЫЙ СЦЕНАРИЙ")
    script = create_video_script(
        session,
        VideoScriptRequest(season_id=imported.season.id, story_arc_id=arc.id),
        settings,
    )
    assert script.script_text == "ГОТОВЫЙ СЦЕНАРИЙ"


def test_local_text_and_voice_profile_v2_are_backward_safe(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [None]}

    monkeypatch.setattr("app.analysis.local_text.httpx.post", lambda *_args, **_kwargs: Response())
    assert generate_local_text(Settings(llm_adapter="llama-cpp-http"), "тест") is None

    first = np.zeros(76, dtype=np.float32)
    second = np.zeros(76, dtype=np.float32)
    first[0] = 1
    second[1] = 1
    payload = merge_voice_profile(None, VoiceEmbedding(first, 2, 4.0, (first, second)))
    restored = voice_profile_from_json(7, "Герой", payload)

    assert payload["version"] == 2
    assert len(payload["prototypes"]) == 2
    assert restored is not None and len(restored.prototypes) == 2
