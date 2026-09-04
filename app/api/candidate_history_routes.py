from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api._shared import _ensure_episode_not_enqueued
from app.api.dependencies import get_session
from app.api.schemas import CandidateSnapshotRead
from app.application.processing_guard import ProcessingBusyError
from app.models.entities import ClipCandidate
from app.application.edit_history import list_candidate_snapshots, restore_candidate_snapshot

router = APIRouter(prefix="/api")


@router.get("/candidates/{candidate_id}/history", response_model=list[CandidateSnapshotRead])
def candidate_history(candidate_id: int, session: Session = Depends(get_session)):
    try:
        return list_candidate_snapshots(session, candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/candidates/{candidate_id}/history/{snapshot_id}/restore",
    response_model=CandidateSnapshotRead,
)
def restore_candidate_history(
    candidate_id: int,
    snapshot_id: int,
    session: Session = Depends(get_session),
):
    try:
        _ensure_episode_not_enqueued(
            session,
            _candidate_episode_id(session, candidate_id),
        )
        result = restore_candidate_snapshot(session, candidate_id, snapshot_id)
        session.commit()
        return result
    except ProcessingBusyError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _candidate_episode_id(session: Session, candidate_id: int) -> int:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    return candidate.episode_id
