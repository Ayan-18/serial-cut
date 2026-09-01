from __future__ import annotations

from app.api._shared import *  # noqa: F403
from app.application.batch_ops import batch_enqueue_candidate_renders, batch_review_candidates

router = APIRouter(prefix="/api")


@router.post(
    "/episodes/{episode_id}/candidates/batch-review",
    response_model=BatchOutcomeRead,
)
def batch_review(
    episode_id: int,
    payload: BatchReviewRequest,
    session: Session = Depends(get_session),
):
    try:
        _get_episode(session, episode_id)
        _ensure_episode_not_enqueued(session, episode_id)
        outcome = batch_review_candidates(
            session, episode_id, payload.candidate_ids, payload.decision
        )
        session.commit()
        return outcome
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/candidates/batch-render-job", response_model=BatchOutcomeRead)
def batch_render_job(payload: BatchRenderRequest, session: Session = Depends(get_session)):
    render_payload = payload.model_dump(exclude={"candidate_ids"})
    try:
        outcome = batch_enqueue_candidate_renders(
            session, payload.candidate_ids, render_payload
        )
        session.commit()
        return outcome
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
