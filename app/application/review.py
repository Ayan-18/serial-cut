from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    Episode,
    Export,
    ReviewDecision,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    TranscriptSegment,
)


@dataclass(frozen=True)
class ReviewResult:
    candidate_id: int
    status: str
    decision_id: int


@dataclass(frozen=True)
class CandidateEditResult:
    candidate_id: int
    status: str


def save_candidate_edits(
    session: Session,
    candidate_id: int,
    adjusted_start_time: float | None = None,
    adjusted_end_time: float | None = None,
    crop_mode: str | None = None,
    crop_offset_x: float | None = None,
    crop_scale: float | None = None,
) -> CandidateEditResult:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    _apply_candidate_edits(
        session,
        candidate,
        adjusted_start_time,
        adjusted_end_time,
        crop_mode,
        crop_offset_x,
        crop_scale,
    )
    return CandidateEditResult(candidate_id=candidate_id, status=candidate.status)


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
    _apply_candidate_edits(
        session,
        candidate,
        adjusted_start_time,
        adjusted_end_time,
        crop_mode,
        crop_offset_x,
        crop_scale,
    )
    if adjusted_start_time is not None:
        existing.adjusted_start_time = candidate.start_time
    if adjusted_end_time is not None:
        existing.adjusted_end_time = candidate.end_time
    candidate.status = "approved" if decision == "approve" else "rejected"
    return ReviewResult(candidate_id=candidate_id, status=candidate.status, decision_id=existing.id)


def _apply_candidate_edits(
    session: Session,
    candidate: ClipCandidate,
    adjusted_start_time: float | None = None,
    adjusted_end_time: float | None = None,
    crop_mode: str | None = None,
    crop_offset_x: float | None = None,
    crop_scale: float | None = None,
) -> None:
    next_start = candidate.start_time if adjusted_start_time is None else adjusted_start_time
    next_end = candidate.end_time if adjusted_end_time is None else adjusted_end_time
    if adjusted_start_time is not None:
        next_start = _snap_speech_boundary(session, candidate.episode_id, next_start, is_start=True)
    if adjusted_end_time is not None:
        next_end = _snap_speech_boundary(session, candidate.episode_id, next_end, is_start=False)
    if next_start < 0 or next_end <= next_start:
        raise ValueError("Конец кандидата должен быть позже начала")
    episode = session.get(Episode, candidate.episode_id)
    if episode is not None and episode.duration_seconds is not None and next_end > episode.duration_seconds + 0.05:
        raise ValueError("Конец кандидата выходит за длительность серии")

    boundary_changed = (
        abs(candidate.start_time - next_start) > 0.01
        or abs(candidate.end_time - next_end) > 0.01
    )
    next_crop_mode = candidate.crop_mode if crop_mode is None else crop_mode
    next_offset = candidate.crop_offset_x if crop_offset_x is None else max(-1.0, min(1.0, crop_offset_x))
    next_scale = candidate.crop_scale if crop_scale is None else max(1.0, min(2.0, crop_scale))
    visual_changed = (
        next_crop_mode != candidate.crop_mode
        or abs(next_offset - candidate.crop_offset_x) > 0.001
        or abs(next_scale - candidate.crop_scale) > 0.001
    )
    if not boundary_changed and not visual_changed:
        return

    from app.application.edit_history import record_candidate_snapshot

    if boundary_changed and visual_changed:
        record_candidate_snapshot(session, candidate, "boundaries", "Границы и кадр")
    elif boundary_changed:
        record_candidate_snapshot(session, candidate, "boundaries", "Границы клипа")
    else:
        record_candidate_snapshot(session, candidate, "crop", "Кадрирование")

    # The auto-follow trajectory is indexed to the clip's time range, so keep it
    # across pure crop tweaks (offset/scale) and only drop it when the boundaries
    # move or the user leaves auto-follow.
    keeps_trajectory = (
        not boundary_changed
        and next_crop_mode == "auto-follow"
        and candidate.crop_mode == "auto-follow"
    )
    candidate.start_time = next_start
    candidate.end_time = next_end
    candidate.crop_mode = next_crop_mode
    candidate.crop_offset_x = next_offset
    candidate.crop_scale = next_scale
    if not keeps_trajectory:
        candidate.crop_keyframes_json = []
    candidate.thumbnail_path = None
    candidate.edit_revision += 1
    if candidate.status == "rendered":
        candidate.status = "approved"
    invalidate_candidate_derivatives(session, candidate, boundary_changed)


def _snap_speech_boundary(session: Session, episode_id: int, value: float, is_start: bool) -> float:
    segment = session.scalar(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .where(TranscriptSegment.start_time + 0.05 < value)
        .where(TranscriptSegment.end_time - 0.05 > value)
        .order_by(TranscriptSegment.start_time)
    )
    if segment is None:
        return value
    return segment.start_time if is_start else segment.end_time


def invalidate_candidate_derivatives(
    session: Session,
    candidate: ClipCandidate,
    boundary_changed: bool,
) -> None:
    if boundary_changed:
        session.execute(delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate.id))
    for export in session.scalars(select(Export).where(Export.candidate_id == candidate.id)).all():
        export.status = "stale"

    segments = session.scalars(
        select(StoryArcSegment).where(StoryArcSegment.candidate_id == candidate.id)
    ).all()
    arc_ids: set[int] = set()
    for segment in segments:
        arc_ids.add(segment.story_arc_id)
        if boundary_changed and not segment.manually_edited:
            segment.start_time = candidate.start_time
            segment.end_time = candidate.end_time
            segment.candidate_revision = candidate.edit_revision
    for arc_id in arc_ids:
        arc = session.get(StoryArc, arc_id)
        if arc is None:
            continue
        from app.application.story_arcs import refresh_story_arc_plan

        refresh_story_arc_plan(session, arc)
        arc.status = "draft"
        arc.edit_revision += 1
        for export in session.scalars(
            select(StoryArcExport).where(StoryArcExport.story_arc_id == arc.id)
        ).all():
            export.status = "stale"

