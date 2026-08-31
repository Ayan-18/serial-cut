from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, Episode, Job, PublishingPlan, Season, StoryArc, StoryArcSegment, VideoScript


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class ProjectDiagnostics:
    checks: list[DiagnosticCheck]
    recommendations: list[str]
    counts: dict[str, int]


def run_project_diagnostics(session: Session, settings: Settings) -> ProjectDiagnostics:
    counts = {
        "seasons": _count(session, Season),
        "episodes": _count(session, Episode),
        "candidates": _count(session, ClipCandidate),
        "story_arcs": _count(session, StoryArc),
        "video_scripts": _count(session, VideoScript),
        "publishing_plans": _count(session, PublishingPlan),
    }
    missing_files = [
        episode.file_name
        for episode in session.scalars(select(Episode).order_by(Episode.file_name)).all()
        if not Path(episode.file_path).exists()
    ]
    failed_jobs = session.scalars(select(Job).where(Job.status == JobStatus.FAILED.value)).all()
    orphan_segments = session.scalars(
        select(StoryArcSegment)
        .outerjoin(ClipCandidate, ClipCandidate.id == StoryArcSegment.candidate_id)
        .where(StoryArcSegment.candidate_id.is_not(None))
        .where(ClipCandidate.id.is_(None))
    ).all()
    output_dir = settings.output_dir
    cache_dir = settings.cache_dir
    checks = [
        DiagnosticCheck("База проекта", counts["seasons"] > 0, f"{counts['seasons']} сезонов, {counts['episodes']} серий"),
        DiagnosticCheck("Исходные файлы", not missing_files, _missing_message(missing_files)),
        DiagnosticCheck("Очередь", not failed_jobs, f"ошибок: {len(failed_jobs)}"),
        DiagnosticCheck("StoryArc", not orphan_segments, f"планов: {counts['story_arcs']}, битых сегментов: {len(orphan_segments)}"),
        DiagnosticCheck("Output", output_dir.exists(), str(output_dir)),
        DiagnosticCheck("Cache", cache_dir.exists(), str(cache_dir)),
    ]
    recommendations: list[str] = []
    if counts["candidates"] == 0 and counts["episodes"] > 0:
        recommendations.append("Запустите поиск кандидатов хотя бы для одной серии.")
    if counts["story_arcs"] == 0 and counts["candidates"] > 0:
        recommendations.append("Создайте StoryArc из найденных кандидатов сезона.")
    if failed_jobs:
        recommendations.append("Откройте этапы failed-задач и перезапустите с проблемного шага.")
    if missing_files:
        recommendations.append("Проверьте, что внешний диск или папка с сериалом подключены по тому же пути.")
    return ProjectDiagnostics(checks=checks, recommendations=recommendations, counts=counts)


def _count(session: Session, model: type) -> int:
    return len(session.scalars(select(model.id)).all())


def _missing_message(items: list[str]) -> str:
    if not items:
        return "все пути доступны"
    preview = ", ".join(items[:3])
    suffix = f" и ещё {len(items) - 3}" if len(items) > 3 else ""
    return f"нет файлов: {preview}{suffix}"
