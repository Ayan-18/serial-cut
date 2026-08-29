from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ClipCandidate, ReviewDecision


@dataclass(frozen=True)
class ReviewResult:
    candidate_id: int
    status: str
    decision_id: int


def review_candidate(
    session: Session,
    candidate_id: int,
    decision: str,
    adjusted_start_time: float | None = None,
    adjusted_end_time: float | None = None,
    crop_mode: str | None = None,
    reason: str | None = None,
) -> ReviewResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    existing = session.scalar(
        select(ReviewDecision).where(
            ReviewDecision.candidate_id == candidate_id,
            ReviewDecision.decision == decision,
        )
    )
    if existing is None:
        existing = ReviewDecision(
            candidate_id=candidate_id,
            decision=decision,
            adjusted_start_time=adjusted_start_time,
            adjusted_end_time=adjusted_end_time,
            crop_mode=crop_mode,
            reason=reason,
        )
        session.add(existing)
        session.flush()
    if adjusted_start_time is not None:
        candidate.start_time = adjusted_start_time
    if adjusted_end_time is not None:
        candidate.end_time = adjusted_end_time
    if crop_mode is not None:
        candidate.crop_mode = crop_mode
    candidate.status = "approved" if decision == "approve" else "rejected"
    return ReviewResult(candidate_id=candidate_id, status=candidate.status, decision_id=existing.id)

