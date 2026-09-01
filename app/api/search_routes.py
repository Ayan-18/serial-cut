from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.api.schemas import SearchResponse
from app.application.global_search import search_season
from app.models.entities import Season


router = APIRouter(prefix="/api", tags=["search"])


@router.get("/seasons/{season_id}/search", response_model=SearchResponse)
def search_season_endpoint(
    season_id: int,
    q: str,
    limit: int = 30,
    session: Session = Depends(get_session),
) -> SearchResponse:
    if session.get(Season, season_id) is None:
        raise HTTPException(status_code=404, detail="Сезон не найден")
    return SearchResponse(query=q, results=search_season(session, season_id, q, max(1, min(limit, 100))))
