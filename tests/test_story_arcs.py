from __future__ import annotations

from pathlib import Path

from app.application.importer import import_season
from app.application.story_arc_render import concat_list_text, render_story_arc
from app.application.story_arcs import StoryArcPlanRequest, create_story_arc_plan, list_story_arcs
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessResult
from app.models.entities import Character, ClipCandidate, SpeakerIdentity, TranscriptSegment


def _candidate(episode_id: int, start: float, end: float, title: str, score: int = 80) -> ClipCandidate:
    return ClipCandidate(
        episode_id=episode_id,
        start_time=start,
        end_time=end,
        title=title,
        description=f"{title} меняет ход сюжетной линии.",
        moment_type="откровение",
        score=score,
        scores_json={},
        rationale="Понятно без полного контекста",
        problems_json=[],
    )


def test_story_arc_plan_uses_candidates_across_season(session, tmp_path):
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    for index in range(1, 4):
        (season_dir / f"s01e{index:02}.mkv").write_bytes(f"video-{index}".encode("utf-8"))
    imported = import_season(session, season_dir)
    for index, episode_id in enumerate(imported.episode_ids, start=1):
        session.add(_candidate(episode_id, 10, 50, f"Поворот {index}", 80 + index))
    session.flush()

    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(
            season_id=imported.season.id,
            prompt="главный поворот",
            output_format="shorts_series",
            max_segments=3,
            max_duration_seconds=180,
        ),
    )

    assert arc.title == "главный поворот"
    assert len(arc.segments) == 3
    assert [segment.sort_order for segment in arc.segments] == [1, 2, 3]
    assert len({segment.episode_id for segment in arc.segments}) == 3
    assert arc.plan_json["format"] == "shorts_series"
    assert list_story_arcs(session, imported.season.id)[0].id == arc.id


def test_story_arc_plan_can_prioritize_target_character(session, tmp_path):
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    (season_dir / "s01e01.mkv").write_bytes(b"video")
    imported = import_season(session, season_dir)
    episode_id = imported.episode_ids[0]
    character = Character(season_id=imported.season.id, name="Питер", description="", aliases_json=[], photos_json=[])
    session.add(character)
    session.flush()
    session.add(SpeakerIdentity(episode_id=episode_id, source_label="Говорящий 1", character_id=character.id))
    session.add(TranscriptSegment(episode_id=episode_id, start_time=0, end_time=30, text="Я должен понять силу.", speaker_label="Говорящий 1"))
    session.add(_candidate(episode_id, 0, 30, "Персонаж открывает силу", 70))
    session.add(_candidate(episode_id, 40, 70, "Сильная сцена без персонажа", 86))
    session.flush()

    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(
            season_id=imported.season.id,
            arc_type="character",
            target_character_id=character.id,
            max_segments=1,
            max_duration_seconds=60,
        ),
    )

    assert arc.target_character_id == character.id
    assert arc.segments[0].title == "Персонаж открывает силу"
    assert "реплики персонажа" in arc.segments[0].note


def test_story_arc_render_builds_segments_and_concat_export(session, tmp_path, monkeypatch):
    season_dir = tmp_path / "season"
    season_dir.mkdir()
    for index in range(1, 3):
        (season_dir / f"s01e{index:02}.mkv").write_bytes(f"video-{index}".encode("utf-8"))
    imported = import_season(session, season_dir)
    for index, episode_id in enumerate(imported.episode_ids, start=1):
        session.add(_candidate(episode_id, 10, 40, f"Часть {index}", 80 + index))
    session.flush()
    arc = create_story_arc_plan(
        session,
        StoryArcPlanRequest(season_id=imported.season.id, max_segments=2, max_duration_seconds=90),
    )
    rendered_segments: list[Path] = []

    def fake_render_clip(*args, **kwargs):
        output_dir = Path(args[2])
        slug = args[3]
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{slug}.mp4"
        metadata_path = output_dir / f"{slug}.json"
        cover_path = output_dir / f"{slug}.jpg"
        output_path.write_bytes(b"segment")
        metadata_path.write_text("{}", encoding="utf-8")
        cover_path.write_bytes(b"cover")
        rendered_segments.append(output_path)
        return type(
            "Artifacts",
            (),
            {"output_path": output_path, "metadata_path": metadata_path, "subtitle_path": None, "cover_path": cover_path},
        )()

    def fake_runner(args: list[str], timeout: int) -> ProcessResult:
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"concat")
        return ProcessResult(args, 0, "", "")

    monkeypatch.setattr("app.application.story_arc_render.render_clip", fake_render_clip)
    monkeypatch.setattr("app.application.story_arc_render.detect_nvenc", lambda *args, **kwargs: False)

    result = render_story_arc(
        session,
        arc.id,
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        runner=fake_runner,
        force_rerender=True,
        transition_style="fade",
    )

    assert result.segment_count == 2
    assert Path(result.output_path).read_bytes() == b"concat"
    assert Path(result.metadata_path or "").read_text(encoding="utf-8")
    assert len(rendered_segments) == 2
    assert "file '" in concat_list_text(rendered_segments)
    assert result.duration_seconds == 59.75

    reused = render_story_arc(
        session,
        arc.id,
        Settings(cache_dir=tmp_path / "cache", output_dir=tmp_path / "out"),
        runner=fake_runner,
        transition_style="fade",
    )
    assert reused.export_id == result.export_id
    assert reused.duration_seconds == 59.75
