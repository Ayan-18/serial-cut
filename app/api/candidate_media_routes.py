from __future__ import annotations

from app.api._shared import *  # noqa: F403
from app.application.candidate_keyframes import build_candidate_keyframes, candidate_keyframe_file

router = APIRouter(prefix="/api")


@router.get("/candidates/{candidate_id}/keyframes", response_model=KeyframeStripRead)
def candidate_keyframes(
    candidate_id: int,
    count: int = 8,
    session: Session = Depends(get_session),
):
    settings = effective_settings(session, get_settings())
    try:
        with processing_guard():
            return build_candidate_keyframes(session, candidate_id, settings, count)
    except ProcessingBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/candidates/{candidate_id}/keyframes/{index}")
def candidate_keyframe_image(
    candidate_id: int,
    index: int,
    session: Session = Depends(get_session),
):
    settings = effective_settings(session, get_settings())
    try:
        path = candidate_keyframe_file(session, candidate_id, settings, index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _safe_file_response(
        settings,
        str(path),
        media_type="image/jpeg",
        missing_detail="Кадр не найден",
    )
