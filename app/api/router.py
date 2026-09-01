from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    candidate_history_routes,
    candidates_routes,
    characters_routes,
    episodes_routes,
    exports_routes,
    publishing_routes,
    seasons_routes,
    settings_and_diagnostics_routes,
    story_arcs_routes,
)

router = APIRouter()
domain_routers = (
    settings_and_diagnostics_routes.router,
    seasons_routes.router,
    story_arcs_routes.router,
    publishing_routes.router,
    characters_routes.router,
    episodes_routes.router,
    candidates_routes.router,
    candidate_history_routes.router,
    exports_routes.router,
)

for domain_router in domain_routers:
    router.routes.extend(domain_router.routes)
