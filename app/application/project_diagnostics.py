from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.domain.enums import JobStatus
from app.infrastructure.config import Settings
from app.models.entities import (
    ClipCandidate,
    Episode,
    Export,
    Job,
    PublishingPlan,
    Season,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    VideoScript,
)


EXPECTED_DB_REVISION = "0011_job_stage_consistency"


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
    missing_exports = [
        item.output_path
        for item in [
            *session.scalars(select(Export).where(Export.status == "completed")).all(),
            *session.scalars(select(StoryArcExport).where(StoryArcExport.status == "completed")).all(),
        ]
        if not Path(item.output_path).exists()
    ]
    stale_exports = int(session.scalar(select(func.count(Export.id)).where(Export.status == "stale")) or 0)
    stale_story_exports = int(
        session.scalar(select(func.count(StoryArcExport.id)).where(StoryArcExport.status == "stale")) or 0
    )
    db_revision = _database_revision(session)
    free_bytes = _free_bytes(output_dir)
    ffmpeg_ready = _tool_exists(settings.ffmpeg_path)
    ffprobe_ready = _tool_exists(settings.ffprobe_path)
    checks = [
        DiagnosticCheck("База проекта", counts["seasons"] > 0, f"{counts['seasons']} сезонов, {counts['episodes']} серий"),
        DiagnosticCheck(
            "Миграция базы",
            db_revision in {None, EXPECTED_DB_REVISION},
            db_revision or "чистая тестовая база",
        ),
        DiagnosticCheck("Исходные файлы", not missing_files, _missing_message(missing_files)),
        DiagnosticCheck("Очередь", not failed_jobs, f"ошибок: {len(failed_jobs)}"),
        DiagnosticCheck("StoryArc", not orphan_segments, f"планов: {counts['story_arcs']}, битых сегментов: {len(orphan_segments)}"),
        DiagnosticCheck("FFmpeg", ffmpeg_ready and ffprobe_ready, f"ffmpeg: {ffmpeg_ready}, ffprobe: {ffprobe_ready}"),
        DiagnosticCheck("Экспорты", not missing_exports, f"потерянных файлов: {len(missing_exports)}"),
        DiagnosticCheck(
            "Актуальность рендера",
            stale_exports + stale_story_exports == 0,
            f"устаревших: {stale_exports + stale_story_exports}",
        ),
        DiagnosticCheck(
            "Свободное место",
            free_bytes is None or free_bytes >= 2 * 1024**3,
            _format_bytes(free_bytes) if free_bytes is not None else "не удалось определить",
        ),
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
    if db_revision not in {None, EXPECTED_DB_REVISION}:
        recommendations.append("Перезапустите приложение штатным scripts\\run.ps1, чтобы применить миграции базы.")
    if not ffmpeg_ready or not ffprobe_ready:
        recommendations.append("Укажите рабочие FFmpeg/ffprobe в .env или добавьте их в PATH.")
    if missing_exports:
        recommendations.append("Перерендерите записи, чьи готовые MP4 больше не найдены на диске.")
    if stale_exports + stale_story_exports:
        recommendations.append("Перерендерите устаревшие клипы после последних правок границ или кадрирования.")
    if free_bytes is not None and free_bytes < 2 * 1024**3:
        recommendations.append("Освободите минимум 2 ГБ в папке output перед длинным рендером.")
    if settings.asr_adapter == "stub" or settings.llm_adapter == "stub":
        recommendations.append("Для реального анализа включите faster-whisper и llama.cpp через .env.")
    return ProjectDiagnostics(checks=checks, recommendations=recommendations, counts=counts)


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def _missing_message(items: list[str]) -> str:
    if not items:
        return "все пути доступны"
    preview = ", ".join(items[:3])
    suffix = f" и ещё {len(items) - 3}" if len(items) > 3 else ""
    return f"нет файлов: {preview}{suffix}"


def _database_revision(session: Session) -> str | None:
    bind = session.get_bind()
    if "alembic_version" not in inspect(bind).get_table_names():
        return None
    return session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()


def _tool_exists(value: str) -> bool:
    path = Path(value)
    return path.exists() if path.parent != Path(".") else shutil.which(value) is not None


def _free_bytes(path: Path) -> int | None:
    try:
        probe = path if path.exists() else path.resolve().anchor
        return shutil.disk_usage(probe).free
    except (OSError, ValueError):
        return None


def _format_bytes(value: int) -> str:
    return f"{value / 1024**3:.1f} ГБ свободно"
