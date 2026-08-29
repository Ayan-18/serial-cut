from __future__ import annotations

from sqlalchemy import select

from app.application.auto import auto_approve_and_export
from app.application.importer import import_season
from app.application.queue_control import set_queue_paused
from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, JobStage
from app.workers.queue import enqueue_season_analysis
from app.workers.runner import run_next_job


def _episode_with_candidate(session, tmp_path, score: int = 90) -> tuple[int, int]:
    season = tmp_path / "Сезон"
    season.mkdir(exist_ok=True)
    (season / f"episode-{score}.mkv").write_bytes(b"video")
    imported = import_season(session, season)
    episode_id = imported.episode_ids[-1]
    candidate = ClipCandidate(
        episode_id=episode_id,
        start_time=0,
        end_time=35,
        title="Тест",
        description="Описание",
        moment_type="другое",
        score=score,
        scores_json={},
        rationale="Понятен",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()
    return episode_id, candidate.id


def test_auto_export_applies_threshold_limit_and_is_idempotent(session, tmp_path, monkeypatch):
    episode_id, candidate_id = _episode_with_candidate(session, tmp_path, score=95)

    def fake_render(session, candidate_id, settings, include_subtitles=True, use_nvenc=False):
        return type("Rendered", (), {"output_path": f"C:/out/{candidate_id}.mp4"})()

    monkeypatch.setattr("app.application.auto.render_candidate", fake_render)
    result = auto_approve_and_export(session, episode_id, Settings(), threshold=90, max_clips=1, use_nvenc=False)

    assert result.approved == 1
    assert result.rendered == 1
    assert session.get(ClipCandidate, candidate_id).status == "approved"


def test_worker_respects_pause_and_runs_queued_job(session, tmp_path):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    imported = import_season(session, season)
    jobs = enqueue_season_analysis(session, imported.season.id)
    session.commit()

    set_queue_paused(session, True)
    paused = run_next_job(session, Settings(), stage2_func=lambda *args: None, stage3_func=lambda *args: None)
    assert paused.status == "paused"

    set_queue_paused(session, False)
    result = run_next_job(session, Settings(), stage2_func=lambda *args: None, stage3_func=lambda *args: None)
    session.commit()

    assert result.ran is True
    assert session.get(type(jobs[0]), jobs[0].id).status == JobStatus.COMPLETED.value
    assert len(session.scalars(select(JobStage)).all()) == 2

