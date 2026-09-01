from __future__ import annotations

from pathlib import Path

from app.application.log_reader import read_log_tail
from app.application.runtime_info import BOOT_ID


def test_health_reports_version_boot_id_and_queue(api_client):
    response = api_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "SerialCuts"
    assert body["boot_id"] == BOOT_ID
    assert body["version"]
    assert len(body["token_fingerprint"]) == 12
    assert body["queue"]["state"] == "running"


def test_version_endpoint_matches_health_boot_id(api_client):
    health = api_client.get("/api/health").json()
    version = api_client.get("/api/version").json()

    assert version["boot_id"] == health["boot_id"]
    assert version["version"] == health["version"]


def test_logs_endpoint_returns_recent_lines(api_client):
    response = api_client.get("/api/logs", params={"lines": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["returned"] <= 5
    assert isinstance(body["entries"], list)


def test_read_log_tail_filters_by_level_and_search(tmp_path: Path):
    log_path = tmp_path / "serialcuts.log"
    log_path.write_text(
        "2026-09-02 01:00:00,000 INFO app.workers.runner: Job started id=1\n"
        "2026-09-02 01:00:01,000 WARNING app.media.ffmpeg: NVENC render failed\n"
        "2026-09-02 01:00:02,000 ERROR app.api.errors: Unhandled API error\n"
        "  Traceback continuation line\n",
        encoding="utf-8",
    )

    warnings = read_log_tail(lines=50, min_level="WARNING", log_path=log_path)
    assert [entry.level for entry in warnings.entries] == ["WARNING", "ERROR"]

    matched = read_log_tail(lines=50, search="nvenc", log_path=log_path)
    assert len(matched.entries) == 1
    assert "NVENC" in matched.entries[0].message

    errors = read_log_tail(lines=50, min_level="ERROR", log_path=log_path)
    assert errors.entries[0].message.endswith("Traceback continuation line")
