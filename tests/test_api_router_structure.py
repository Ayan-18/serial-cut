from __future__ import annotations

from pathlib import Path

from app.api.router import domain_routers


def test_domain_routers_expose_expected_api_paths():
    paths = {
        route.path
        for domain_router in domain_routers
        for route in domain_router.routes
        if getattr(route, "path", "").startswith("/api")
    }

    assert "/api/health" in paths
    assert "/api/seasons/import" in paths
    assert "/api/episodes/{episode_id}/stage2" in paths
    assert "/api/candidates/{candidate_id}/render" in paths
    assert "/api/story-arcs/{story_arc_id}/render-job" in paths
    assert "/api/publishing-plans/{plan_id}/package" in paths


def test_api_route_modules_stay_small():
    api_dir = Path(__file__).resolve().parents[1] / "app" / "api"
    # `schemas.py` holds every Pydantic model; `_shared.py` holds the shared
    # HTTP helpers and their explicit imports. Neither defines routes.
    allowed_large_modules = {"schemas.py", "_shared.py"}
    for path in api_dir.glob("*.py"):
        if path.name in allowed_large_modules:
            continue
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 300, path.name
