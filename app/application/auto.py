from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.review import review_candidate
from app.application.stage4 import RenderResult, render_candidate
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate


@dataclass(frozen=True)
class AutoExportResult:
    approved: int
    rendered: int
    skipped: int
    export_paths: list[str]


def auto_approve_and_export(
    session: Session,
    episode_id: int,
    settings: Settings,
    threshold: int,
    max_clips: int,
    use_nvenc: bool,
) -> AutoExportResult:
    candidates = session.scalars(
        select(ClipCandidate)
        .where(ClipCandidate.episode_id == episode_id)
        .where(ClipCandidate.score >= threshold)
        .where(ClipCandidate.status != "rejected")
        .order_by(ClipCandidate.score.desc(), ClipCandidate.start_time)
    ).all()
    approved = 0
    rendered = 0
    exports: list[str] = []
    for candidate in candidates[:max_clips]:
        if candidate.crop_mode not in {"center-crop", "auto-follow", "blurred-background"}:
            candidate.crop_mode = "blurred-background"
        review_candidate(session, candidate.id, "approve", crop_mode=candidate.crop_mode)
        approved += 1
        export = render_candidate(session, candidate.id, settings, include_subtitles=True, use_nvenc=use_nvenc)
        rendered += 1
        exports.append(export.output_path)
    return AutoExportResult(
        approved=approved,
        rendered=rendered,
        skipped=max(0, len(candidates) - max_clips),
        export_paths=exports,
    )

