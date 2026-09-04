from __future__ import annotations

import contextlib
import json

from app.api import events_routes
from app.domain.enums import JobKind, JobStatus
from app.models.entities import Episode, Job, Season


def _episode(session) -> int:
    season = Season(title="S", root_path="C:/events-demo")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/events-demo/e.mkv",
        file_name="e.mkv",
        fingerprint="fp-events",
        size_bytes=1,
        modified_ns=1,
    )
    session.add(episode)
    session.flush()
    return episode.id


def test_queue_payload_serializes_snapshot_and_items(session, monkeypatch):
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
    session.flush()

    @contextlib.contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(events_routes, "session_scope", fake_scope)

    payload = json.loads(events_routes._queue_payload())
    assert payload["snapshot"]["queued"] == 1
    assert payload["snapshot"]["paused"] is False
    assert payload["items"][0]["current_stage"] == "stage2_media"


def test_events_route_is_registered(api_client):
    # POST is not allowed on the stream; a 405 proves the GET route is wired up
    # without opening the (endless) stream itself.
    assert api_client.post("/api/events").status_code == 405
