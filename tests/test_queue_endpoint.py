from __future__ import annotations

from app.domain.enums import JobKind, JobStatus
from app.models.entities import Episode, Job, Season


def _episode(session) -> int:
    season = Season(title="S", root_path="C:/queue-demo")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/queue-demo/e.mkv",
        file_name="e.mkv",
        fingerprint="fp-queue-endpoint",
        size_bytes=1,
        modified_ns=1,
    )
    session.add(episode)
    session.flush()
    return episode.id


def test_jobs_endpoint_serializes_snapshot_and_items(api_client):
    session = api_client.db
    episode_id = _episode(session)
    session.add(
        Job(
            episode_id=episode_id,
            kind=JobKind.ANALYZE_EPISODE.value,
            status=JobStatus.QUEUED.value,
            current_stage="stage2_media",
            progress=0.0,
        )
    )
    session.commit()

    response = api_client.get("/api/jobs")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot"] == {
        "queued": 1,
        "running": 0,
        "failed": 0,
        "paused": False,
        "eta_seconds": body["snapshot"]["eta_seconds"],
    }
    assert len(body["items"]) == 1
    assert body["items"][0]["kind"] == "analyze_episode"
    assert body["items"][0]["current_stage"] == "stage2_media"


def test_jobs_endpoint_is_empty_without_jobs(api_client):
    response = api_client.get("/api/jobs")
    assert response.status_code == 200
    assert response.json() == {
        "snapshot": {"queued": 0, "running": 0, "failed": 0, "paused": False, "eta_seconds": None},
        "items": [],
    }
