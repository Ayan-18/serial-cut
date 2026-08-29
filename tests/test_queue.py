from __future__ import annotations

from app.application.importer import import_season
from app.domain.enums import JobStatus
from app.workers.queue import enqueue_episode_analysis, recover_interrupted_jobs, retry_job


def test_job_recovery_returns_running_job_to_queue(session, tmp_path):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    result = import_season(session, season)
    job = enqueue_episode_analysis(session, result.episode_ids[0])
    job.status = JobStatus.RUNNING.value
    session.commit()

    recovered = recover_interrupted_jobs(session)
    session.commit()

    assert recovered == 1
    assert job.status == JobStatus.QUEUED.value
    assert "восстановлена" in (job.error_message or "")


def test_cancelled_job_can_be_retried_idempotently(session, tmp_path):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    result = import_season(session, season)
    job = enqueue_episode_analysis(session, result.episode_ids[0])
    job.status = JobStatus.FAILED.value
    job.error_message = "boom"

    retry_job(session, job.id)

    assert job.status == JobStatus.QUEUED.value
    assert job.error_message is None
    assert job.attempts == 1

