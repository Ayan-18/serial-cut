from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.entities import CandidateEditSnapshot, CandidateSubtitle, ClipCandidate

MAX_SNAPSHOTS_PER_CANDIDATE = 25


@dataclass(frozen=True)
class SnapshotEntry:
    id: int
    candidate_id: int
    edit_revision: int
    kind: str
    label: str
    created_at: datetime
    start_time: float
    end_time: float
    crop_mode: str
    subtitle_rows: int


def _raw_subtitles(session: Session, candidate_id: int) -> list[dict]:
    rows = session.scalars(
        select(CandidateSubtitle)
        .where(CandidateSubtitle.candidate_id == candidate_id)
        .order_by(CandidateSubtitle.sort_order, CandidateSubtitle.start_time)
    ).all()
    return [
        {
            "start_time": row.start_time,
            "end_time": row.end_time,
            "text": row.text,
            "speaker_label": row.speaker_label,
            "sort_order": row.sort_order,
        }
        for row in rows
    ]


def _candidate_state(session: Session, candidate: ClipCandidate) -> dict:
    return {
        "start_time": candidate.start_time,
        "end_time": candidate.end_time,
        "crop_mode": candidate.crop_mode,
        "crop_offset_x": candidate.crop_offset_x,
        "crop_scale": candidate.crop_scale,
        "crop_keyframes_json": list(candidate.crop_keyframes_json or []),
        "subtitles": _raw_subtitles(session, candidate.id),
        "has_saved_subtitles": bool(
            session.scalar(
                select(CandidateSubtitle.id).where(CandidateSubtitle.candidate_id == candidate.id).limit(1)
            )
        ),
    }


def record_candidate_snapshot(
    session: Session,
    candidate: ClipCandidate,
    kind: str,
    label: str,
) -> CandidateEditSnapshot:
    """Store the candidate's current geometry + subtitles so an edit can be undone."""
    snapshot = CandidateEditSnapshot(
        candidate_id=candidate.id,
        edit_revision=candidate.edit_revision,
        kind=kind,
        label=label,
        state_json=_candidate_state(session, candidate),
    )
    session.add(snapshot)
    session.flush()
    _prune(session, candidate.id)
    return snapshot


def _prune(session: Session, candidate_id: int) -> None:
    ids = list(
        session.scalars(
            select(CandidateEditSnapshot.id)
            .where(CandidateEditSnapshot.candidate_id == candidate_id)
            .order_by(CandidateEditSnapshot.id.desc())
        ).all()
    )
    stale = ids[MAX_SNAPSHOTS_PER_CANDIDATE:]
    if stale:
        session.execute(
            delete(CandidateEditSnapshot).where(CandidateEditSnapshot.id.in_(stale))
        )


def list_candidate_snapshots(session: Session, candidate_id: int) -> list[SnapshotEntry]:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    rows = session.scalars(
        select(CandidateEditSnapshot)
        .where(CandidateEditSnapshot.candidate_id == candidate_id)
        .order_by(CandidateEditSnapshot.id.desc())
    ).all()
    return [
        SnapshotEntry(
            id=row.id,
            candidate_id=row.candidate_id,
            edit_revision=row.edit_revision,
            kind=row.kind,
            label=row.label,
            created_at=row.created_at,
            start_time=float(row.state_json.get("start_time", 0.0)),
            end_time=float(row.state_json.get("end_time", 0.0)),
            crop_mode=str(row.state_json.get("crop_mode", "")),
            subtitle_rows=len(row.state_json.get("subtitles", [])),
        )
        for row in rows
    ]


def restore_candidate_snapshot(
    session: Session,
    candidate_id: int,
    snapshot_id: int,
) -> SnapshotEntry:
    from app.application.review import invalidate_candidate_derivatives

    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    snapshot = session.get(CandidateEditSnapshot, snapshot_id)
    if snapshot is None or snapshot.candidate_id != candidate_id:
        raise ValueError("Снимок правок не найден для этого кандидата")

    # Keep the state we are leaving so the restore itself is undoable.
    record_candidate_snapshot(session, candidate, "restore", "Перед откатом")

    state = snapshot.state_json
    candidate.start_time = float(state["start_time"])
    candidate.end_time = float(state["end_time"])
    candidate.crop_mode = str(state["crop_mode"])
    candidate.crop_offset_x = float(state["crop_offset_x"])
    candidate.crop_scale = float(state["crop_scale"])
    candidate.crop_keyframes_json = list(state.get("crop_keyframes_json") or [])
    candidate.thumbnail_path = None
    candidate.edit_revision += 1
    if candidate.status == "rendered":
        candidate.status = "approved"

    session.execute(delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate_id))
    if state.get("has_saved_subtitles"):
        for index, row in enumerate(state.get("subtitles", [])):
            session.add(
                CandidateSubtitle(
                    candidate_id=candidate_id,
                    start_time=float(row["start_time"]),
                    end_time=float(row["end_time"]),
                    text=str(row["text"]),
                    speaker_label=row.get("speaker_label"),
                    sort_order=int(row.get("sort_order", index)),
                )
            )

    invalidate_candidate_derivatives(session, candidate, boundary_changed=True)
    session.flush()
    return SnapshotEntry(
        id=snapshot.id,
        candidate_id=candidate_id,
        edit_revision=candidate.edit_revision,
        kind=snapshot.kind,
        label=snapshot.label,
        created_at=snapshot.created_at,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        crop_mode=candidate.crop_mode,
        subtitle_rows=len(state.get("subtitles", [])),
    )
