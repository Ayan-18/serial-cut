from __future__ import annotations

from app.application.importer import import_season
from app.domain.enums import JobStatus
from app.models.entities import JobStage
from app.workers.queue import enqueue_episode_analysis, recover_interrupted_jobs, retry_job, retry_job_from_stage


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
    job.payload = {"resume_from_stage": "stage3_candidates"}

    retry_job(session, job.id)

    assert job.status == JobStatus.QUEUED.value
    assert job.error_message is None
    assert job.attempts == 1
    assert job.payload is None


def test_failed_job_can_retry_from_selected_stage(session, tmp_path):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    result = import_season(session, season)
    job = enqueue_episode_analysis(session, result.episode_ids[0])
    job.status = JobStatus.FAILED.value
    job.error_message = "stage3 failed"
    stage2 = JobStage(job_id=job.id, name="stage2_media", status=JobStatus.COMPLETED.value)
    stage3 = JobStage(job_id=job.id, name="stage3_candidates", status=JobStatus.FAILED.value, error_message="boom")
    auto_export = JobStage(job_id=job.id, name="auto_export", status=JobStatus.QUEUED.value)
    session.add_all([stage2, stage3, auto_export])
    session.flush()

    retry_job_from_stage(session, job.id, "stage3_candidates")

    assert job.status == JobStatus.QUEUED.value
    assert job.current_stage == "stage3_candidates"
    assert job.payload["resume_from_stage"] == "stage3_candidates"
    assert job.progress == 0.45
    assert job.error_message is None
    assert stage2.status == JobStatus.COMPLETED.value
    assert stage3.status == JobStatus.QUEUED.value
    assert stage3.error_message is None
    assert auto_export.status == JobStatus.QUEUED.value
