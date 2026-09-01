from __future__ import annotations

from pathlib import Path
import wave

from app.application.global_search import search_season
from app.application.importer import import_season
from app.application.narration import story_arc_narration, synthesize_story_arc_narration
from app.application.project_diagnostics import run_project_diagnostics
from app.application.publishing import PublishingPlanRequest, create_publishing_plan
from app.application.story_arcs import (
    StoryArcPlanRequest,
    StoryArcSegmentUpdate,
    add_candidate_to_story_arc,
    create_story_arc_plan,
    update_story_arc_segment,
)
from app.application.video_scripts import VideoScriptRequest, create_video_script
from app.domain.enums import JobKind
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult
from app.models.entities import ClipCandidate, TranscriptSegment
from app.workers.queue import enqueue_story_arc_render
from app.workers.runner import run_next_job


def _candidate(episode_id: int, start: float, end: float, title: str, score: int = 82) -> ClipCandidate:
    return ClipCandidate(
        episode_id=episode_id,
        start_time=start,
        end_time=end,
        title=title,
        description=f"{title}: герой принимает решение.",
        moment_type="перелом героя",
        score=score,
        scores_json={"payoff": score, "standalone_context": score},
        rationale="Понятно без полного контекста",
        problems_json=[],
    )


def _season_with_candidates(session, tmp_path: Path):
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    for index in range(1, 4):
        (season_dir / f"s01e{index:02}.mkv").write_bytes(f"video-{index}".encode("utf-8"))
    imported = import_season(session, season_dir)
    for index, episode_id in enumerate(imported.episode_ids, start=1):
        session.add(_candidate(episode_id, 10 * index, 10 * index + 35, f"Решение героя {index}", 80 + index))
        session.add(
            TranscriptSegment(
                episode_id=episode_id,
                start_time=10 * index,
                end_time=10 * index + 6,
                text=f"Герой говорит важную правду номер {index}",
                speaker_label="Герой",
            )
        )
    session.flush()
    return imported


def test_story_arc_editor_search_script_publish_and_diagnostics(session, tmp_path):
    imported = _season_with_candidates(session, tmp_path)
    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(
            season_id=imported.season.id,
            prompt="важную правду",
            max_segments=2,
            max_duration_seconds=120,
        ),
    )
    first = arc.segments[0]
    previous_duration = arc.total_duration_seconds
    updated = update_story_arc_segment(
        session,
        arc.id,
        first.id,
        StoryArcSegmentUpdate(start_time=first.start_time + 1, end_time=first.end_time + 2, title="Новая граница"),
    )

    assert updated.segments[0].title == "Новая граница"
    assert updated.total_duration_seconds > previous_duration
    assert search_season(session, imported.season.id, "важную правду")[0].kind in {"candidate", "transcript"}

    extra_candidate = session.query(ClipCandidate).filter(ClipCandidate.episode_id == imported.episode_ids[-1]).first()
    extended = add_candidate_to_story_arc(session, arc.id, extra_candidate.id)
    assert len(extended.segments) >= 2

    script = create_video_script(
        session,
        VideoScriptRequest(season_id=imported.season.id, story_arc_id=arc.id, prompt="от лица героя"),
    )
    assert "Монтаж:" in script.script_text
    plan = create_publishing_plan(
        session,
        PublishingPlanRequest(season_id=imported.season.id, story_arc_id=arc.id, platform="youtube_shorts"),
    )
    assert "#serialcuts" in plan.hashtags_json

    diagnostics = run_project_diagnostics(session, Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"))
    assert diagnostics.counts["story_arcs"] == 1
    assert any(item.name == "StoryArc" for item in diagnostics.checks)


def test_story_arc_narration_and_queue_render_job(session, tmp_path, monkeypatch):
    imported = _season_with_candidates(session, tmp_path)
    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(season_id=imported.season.id, max_segments=2, max_duration_seconds=120),
    )
    narration = story_arc_narration(session, arc.id)
    assert "показывает важный этап" in narration.text

    def fake_runner(args: list[str], timeout: int) -> ProcessResult:
        output = Path(args[-1])
        if "powershell" in args[0].lower():
            with wave.open(str(output), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16_000)
                handle.writeframes(b"\0\0" * 8_000)
        else:
            output.write_bytes(b"wav")
        return ProcessResult(args, 0, "", "")

    audio = synthesize_story_arc_narration(
        session,
        arc.id,
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        runner=fake_runner,
    )
    assert Path(audio.audio_path).read_bytes() == b"wav"

    calls: list[int] = []

    def fake_render_story_arc(session_arg, story_arc_id, settings, **kwargs):
        calls.append(story_arc_id)

    monkeypatch.setattr("app.workers.runner.render_story_arc", fake_render_story_arc)
    job = enqueue_story_arc_render(session, arc.id, {"include_subtitles": True, "transition_style": "fade"})
    session.commit()

    result = run_next_job(session, Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"))

    assert job.kind == JobKind.RENDER_STORY_ARC.value
    assert result.status == "completed"
    assert calls == [arc.id]
