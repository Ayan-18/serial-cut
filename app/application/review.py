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
    crop_offset_x: float | None = None,
    crop_scale: float | None = None,
    reason: str | None = None,
) -> ReviewResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    next_start = candidate.start_time if adjusted_start_time is None else adjusted_start_time
    next_end = candidate.end_time if adjusted_end_time is None else adjusted_end_time
    if next_start < 0 or next_end <= next_start:
        raise ValueError("Конец кандидата должен быть позже начала")
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
    else:
        existing.adjusted_start_time = adjusted_start_time
        existing.adjusted_end_time = adjusted_end_time
        existing.crop_mode = crop_mode
        existing.reason = reason
    if adjusted_start_time is not None:
        if abs(candidate.start_time - adjusted_start_time) > 0.01:
            candidate.crop_keyframes_json = []
        candidate.start_time = adjusted_start_time
    if adjusted_end_time is not None:
        if abs(candidate.end_time - adjusted_end_time) > 0.01:
            candidate.crop_keyframes_json = []
        candidate.end_time = adjusted_end_time
    if crop_mode is not None:
        candidate.crop_mode = crop_mode
    if crop_offset_x is not None:
        candidate.crop_offset_x = max(-1.0, min(1.0, crop_offset_x))
    if crop_scale is not None:
        candidate.crop_scale = max(1.0, min(2.0, crop_scale))
    candidate.status = "approved" if decision == "approve" else "rejected"
    return ReviewResult(candidate_id=candidate_id, status=candidate.status, decision_id=existing.id)

