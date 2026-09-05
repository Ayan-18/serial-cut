"""MCP server for SerialCuts.

Exposes the local pipeline as MCP tools so Claude Code / Cursor can import a
season, analyse episodes, review and render clips, and build story arcs. It is a
thin client of the app's own loopback HTTP API (``scripts\\run_local.ps1`` must
be running) — no database access, no model loading here.

Run:  powershell -File scripts\\run_mcp.ps1
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

_HOST = os.environ.get("SERIALCUTS_APP_HOST", "127.0.0.1")
_PORT = os.environ.get("SERIALCUTS_APP_PORT", "8090")
_BASE_URL = f"http://{_HOST}:{_PORT}"
_TIMEOUT = 30.0

mcp = FastMCP("serialcuts")
_token: str | None = None


def _client() -> httpx.Client:
    return httpx.Client(base_url=_BASE_URL, timeout=_TIMEOUT)


def _api(
    method: str, path: str, *, json: Any | None = None, params: dict[str, Any] | None = None
) -> Any:
    """One loopback API call. Fetches the per-process token for unsafe methods."""
    global _token
    headers: dict[str, str] = {}
    if method.upper() not in {"GET", "HEAD"}:
        if _token is None:
            with _client() as probe:
                _token = probe.get("/api/security-token").json()["token"]
        headers["X-SerialCuts-Token"] = _token
    try:
        with _client() as client:
            response = client.request(method, path, json=json, params=params, headers=headers)
    except httpx.ConnectError as exc:  # pragma: no cover - offline path
        raise RuntimeError(
            "SerialCuts не запущен. Запустите scripts\\run_local.ps1 и повторите."
        ) from exc
    if response.status_code >= 400:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"HTTP {response.status_code}: {detail}")
    if not response.content:
        return {"ok": True}
    return response.json()


# --- read-only -----------------------------------------------------------------


@mcp.tool()
def health() -> dict:
    """Version, git commit, DB revision and queue state of the running app."""
    return _api("GET", "/api/health")


@mcp.tool()
def list_seasons() -> list[dict]:
    """Every imported season with its episodes (id, file_name, stage, size)."""
    return _api("GET", "/api/seasons")


@mcp.tool()
def list_candidates(episode_id: int) -> list[dict]:
    """Clip candidates found for an episode: score, type, time range, problems."""
    return _api("GET", f"/api/episodes/{episode_id}/candidates")


@mcp.tool()
def episode_quality(episode_id: int) -> dict:
    """Quality summary for an episode: segments, scenes, candidate scores, problems."""
    return _api("GET", f"/api/episodes/{episode_id}/quality")


@mcp.tool()
def candidate_quality(candidate_id: int) -> dict:
    """Score breakdown and concrete fix recommendations for one candidate."""
    return _api("GET", f"/api/candidates/{candidate_id}/quality")


@mcp.tool()
def queue_status() -> dict:
    """Background queue snapshot plus the recent jobs and their stages."""
    return _api("GET", "/api/jobs")


@mcp.tool()
def list_exports() -> list[dict]:
    """Rendered clips: path, preset, candidate, version."""
    return _api("GET", "/api/exports")


@mcp.tool()
def list_story_arcs() -> list[dict]:
    """Saved multi-episode montage plans (StoryArcs) with their segments and exports."""
    return _api("GET", "/api/story-arcs")


@mcp.tool()
def project_diagnostics() -> dict:
    """Migration state, tools, free space, orphaned / stale derived files."""
    return _api("GET", "/api/project-diagnostics")


@mcp.tool()
def model_diagnostics() -> dict:
    """Which local models (Whisper, Qwen, Silero, face) are installed and ready."""
    return _api("GET", "/api/model-diagnostics")


@mcp.tool()
def search_season(season_id: int, query: str) -> dict:
    """Full-text search over the season's candidates and transcripts."""
    return _api("GET", f"/api/seasons/{season_id}/search", params={"q": query})


# --- actions ------------------------------------------------------------------


@mcp.tool()
def import_season(root_path: str, title: str | None = None) -> dict:
    """Import a folder of episode files as a new season. Source files are read-only."""
    return _api("POST", "/api/seasons/import", json={"root_path": root_path, "title": title})


@mcp.tool()
def analyze_episode(episode_id: int) -> dict:
    """Queue full analysis for one episode: media -> speech -> scenes -> candidates."""
    return _api("POST", f"/api/episodes/{episode_id}/enqueue")


@mcp.tool()
def auto_export_episode(episode_id: int) -> dict:
    """Queue analysis and auto-approve + render the top candidates for one episode."""
    return _api("POST", f"/api/episodes/{episode_id}/auto-export")


@mcp.tool()
def analyze_season(season_id: int, auto: bool = False) -> list[dict]:
    """Queue analysis for every episode in a season."""
    return _api("POST", f"/api/seasons/{season_id}/enqueue", json={"auto": auto})


@mcp.tool()
def review_candidate(candidate_id: int, decision: str) -> dict:
    """Approve or reject a candidate. decision is 'approve' or 'reject'."""
    return _api("POST", f"/api/candidates/{candidate_id}/review", json={"decision": decision})


@mcp.tool()
def auto_crop_candidate(candidate_id: int) -> dict:
    """Recompute the scene-aware auto-follow crop trajectory for a candidate."""
    return _api("POST", f"/api/candidates/{candidate_id}/auto-crop")


@mcp.tool()
def render_candidate(candidate_id: int, with_subtitles: bool = True) -> dict:
    """Queue a final vertical render of a candidate."""
    return _api(
        "POST",
        f"/api/candidates/{candidate_id}/render-job",
        json={"include_subtitles": with_subtitles},
    )


@mcp.tool()
def run_queue_next() -> dict:
    """Run the next queued job immediately instead of waiting for the background worker."""
    return _api("POST", "/api/queue/run-next")


@mcp.tool()
def set_queue_paused(paused: bool) -> dict:
    """Pause or resume the background queue."""
    return _api("POST", "/api/queue/pause" if paused else "/api/queue/resume")


@mcp.tool()
def create_story_arc(
    season_id: int,
    prompt: str = "",
    title: str | None = None,
    output_format: str = "shorts_series",
    target_character_id: int | None = None,
    max_segments: int = 8,
    max_duration_seconds: int = 180,
) -> dict:
    """Build a saved montage plan from candidates across the season."""
    return _api(
        "POST",
        "/api/story-arcs",
        json={
            "season_id": season_id,
            "prompt": prompt,
            "title": title,
            "output_format": output_format,
            "target_character_id": target_character_id,
            "max_segments": max_segments,
            "max_duration_seconds": max_duration_seconds,
        },
    )


@mcp.tool()
def render_story_arc(story_arc_id: int, include_subtitles: bool = True) -> dict:
    """Queue a single multi-source MP4 render of a saved StoryArc."""
    return _api(
        "POST",
        f"/api/story-arcs/{story_arc_id}/render-job",
        json={"include_subtitles": include_subtitles},
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
