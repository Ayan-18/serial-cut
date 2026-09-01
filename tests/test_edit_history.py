from __future__ import annotations

from pathlib import Path

import pytest

from app.application.candidate_editor import EditableSubtitle, save_candidate_subtitles, subtitles_for_candidate
from app.application.edit_history import list_candidate_snapshots, restore_candidate_snapshot
from app.application.importer import import_season
from app.application.review import save_candidate_edits
from app.models.entities import ClipCandidate, TranscriptSegment


def _candidate(session, tmp_path: Path) -> ClipCandidate:
    season_dir = tmp_path / "season"
    season_dir.mkdir(parents=True)
    (season_dir / "episode.mkv").write_bytes(b"video")
    episode_id = import_season(session, season_dir).episode_ids[0]
    session.add(
        TranscriptSegment(episode_id=episode_id, start_time=10, end_time=14, text="Первая реплика."),
    )
    session.add(
        TranscriptSegment(episode_id=episode_id, start_time=15, end_time=19, text="Вторая реплика."),
    )
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


def test_boundary_edit_records_snapshot_and_can_be_restored(session, tmp_path: Path):
    candidate = _candidate(session, tmp_path)

    save_candidate_edits(session, candidate.id, adjusted_start_time=11.0, adjusted_end_time=18.0)
    session.flush()

    history = list_candidate_snapshots(session, candidate.id)
    assert len(history) == 1
    assert history[0].kind == "boundaries"
    assert history[0].start_time == 10.0 and history[0].end_time == 20.0

    restore_candidate_snapshot(session, candidate.id, history[0].id)
    session.flush()

    restored = session.get(ClipCandidate, candidate.id)
    assert restored.start_time == 10.0
    assert restored.end_time == 20.0
    # The restore itself is undoable.
    assert list_candidate_snapshots(session, candidate.id)[0].kind == "restore"


def test_subtitle_edits_snapshot_previous_text(session, tmp_path: Path):
    candidate = _candidate(session, tmp_path)

    save_candidate_subtitles(
        session,
        candidate.id,
        [EditableSubtitle(None, 0.0, 3.0, "Оригинальный текст", None)],
    )
    session.flush()
    save_candidate_subtitles(
        session,
        candidate.id,
        [EditableSubtitle(None, 0.0, 3.0, "Переписанный текст", None)],
    )
    session.flush()

    history = list_candidate_snapshots(session, candidate.id)
    assert [entry.kind for entry in history] == ["subtitles", "subtitles"]

    # Oldest snapshot holds the empty (generated) state, the newer one the first save.
    restore_candidate_snapshot(session, candidate.id, history[0].id)
    session.flush()
    assert subtitles_for_candidate(session, candidate.id)[0].text == "Оригинальный текст"


def test_history_endpoints_list_and_restore(api_client):
    session = api_client.db
    from app.models.entities import Episode, Season

    season = Season(title="S", root_path="C:/s")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/s/e.mkv",
        file_name="e.mkv",
        fingerprint="fp-hist",
        size_bytes=1,
        modified_ns=1,
    )
    session.add(episode)
    session.flush()
    candidate = ClipCandidate(
        episode_id=episode.id,
        start_time=10,
        end_time=20,
        title="Момент",
        description="d",
        moment_type="другое",
        score=80,
        scores_json={},
        rationale="r",
        problems_json=[],
    )
    session.add(candidate)
    session.commit()

    assert api_client.get(f"/api/candidates/{candidate.id}/history").json() == []

    api_client.patch(
        f"/api/candidates/{candidate.id}",
        json={"adjusted_start_time": 11.0, "adjusted_end_time": 18.0},
    )
    history = api_client.get(f"/api/candidates/{candidate.id}/history").json()
    assert len(history) == 1

    restored = api_client.post(
        f"/api/candidates/{candidate.id}/history/{history[0]['id']}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["start_time"] == 10.0


def test_restore_rejects_snapshot_from_a_different_candidate(session, tmp_path: Path):
    first = _candidate(session, tmp_path / "a")
    second = _candidate(session, tmp_path / "b")
    save_candidate_edits(session, first.id, adjusted_start_time=11.0, adjusted_end_time=18.0)
    session.flush()
    snapshot_id = list_candidate_snapshots(session, first.id)[0].id

    with pytest.raises(ValueError):
        restore_candidate_snapshot(session, second.id, snapshot_id)
