from __future__ import annotations

from fastapi.testclient import TestClient

from app.application.stage2 import Stage2Result
from app.main import app


def test_stage2_endpoint_returns_pipeline_result(monkeypatch):
    def fake_stage2(session, episode_id, settings):
        return Stage2Result(
            episode_id=episode_id,
            stage="scenes_detected",
            audio_path=r"C:\cache\audio.wav",
            proxy_path=r"C:\cache\proxy.mp4",
            transcript_segments=1,
            scenes=2,
        )

    monkeypatch.setattr("app.api.routes.run_stage2_media_analysis", fake_stage2)

    response = TestClient(app).post("/api/episodes/42/stage2")

    assert response.status_code == 200
    assert response.json()["episode_id"] == 42
    assert response.json()["stage"] == "scenes_detected"
    assert response.json()["transcript_segments"] == 1
    assert response.json()["scenes"] == 2

