from __future__ import annotations

from app.application.importer import import_season
from app.application.story_arcs import StoryArcPlanRequest, create_story_arc_plan, list_story_arcs
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
