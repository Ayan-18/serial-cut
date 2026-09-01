from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.review import review_candidate
from app.models.entities import ClipCandidate, Job
from app.workers.queue import enqueue_candidate_render

MAX_BATCH = 100


@dataclass
class BatchOutcome:
    requested: int
    succeeded: list[int] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    job_ids: list[int] = field(default_factory=list)


def _clean_ids(candidate_ids: list[int]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in candidate_ids:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    if not ordered:
        raise ValueError("Не выбран ни один кандидат")
    if len(ordered) > MAX_BATCH:
        raise ValueError(f"За один раз можно обработать не более {MAX_BATCH} кандидатов")
    return ordered


def batch_review_candidates(
    session: Session,
    episode_id: int,
    candidate_ids: list[int],
    decision: str,
) -> BatchOutcome:
    if decision not in {"approve", "reject"}:
        raise ValueError("decision должен быть approve или reject")
    ordered = _clean_ids(candidate_ids)
    known = {
        row.id
        for row in session.scalars(
            select(ClipCandidate).where(
                ClipCandidate.id.in_(ordered),
                ClipCandidate.episode_id == episode_id,
            )
        ).all()
    }
    outcome = BatchOutcome(requested=len(ordered))
    for candidate_id in ordered:
        if candidate_id not in known:
            outcome.skipped.append({"candidate_id": candidate_id, "reason": "не найден в этой серии"})
            continue
        try:
            review_candidate(session, candidate_id, decision)
            outcome.succeeded.append(candidate_id)
        except ValueError as exc:
            outcome.skipped.append({"candidate_id": candidate_id, "reason": str(exc)})
    return outcome


def batch_enqueue_candidate_renders(
    session: Session,
    candidate_ids: list[int],
    render_payload: dict,
    *,
    require_approved: bool = True,
) -> BatchOutcome:
    ordered = _clean_ids(candidate_ids)
    candidates = {
        row.id: row
        for row in session.scalars(
            select(ClipCandidate).where(ClipCandidate.id.in_(ordered))
        ).all()
    }
    outcome = BatchOutcome(requested=len(ordered))
    for candidate_id in ordered:
        candidate = candidates.get(candidate_id)
        if candidate is None:
            outcome.skipped.append({"candidate_id": candidate_id, "reason": "не найден"})
            continue
        if require_approved and candidate.status not in {"approved", "rendered"}:
            outcome.skipped.append(
                {"candidate_id": candidate_id, "reason": "кандидат не принят"}
            )
            continue
        try:
            job: Job = enqueue_candidate_render(session, candidate_id, dict(render_payload))
        except ValueError as exc:
            outcome.skipped.append({"candidate_id": candidate_id, "reason": str(exc)})
            continue
        session.flush()
        outcome.succeeded.append(candidate_id)
        outcome.job_ids.append(job.id)
    return outcome
