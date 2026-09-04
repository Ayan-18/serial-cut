from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import JobKind, JobStatus
from app.infrastructure.config import Settings
from app.models.entities import AppSetting, ClipCandidate, Episode, Export, Job, StoryArc, StoryArcExport

logger = logging.getLogger(__name__)

# Telegram's bot API caps uploads at 50 MB; stay just under.
_VIDEO_LIMIT_BYTES = 49 * 1024 * 1024
_TERMINAL = {JobStatus.COMPLETED.value, JobStatus.FAILED.value}


def notify_job_finished(session: Session, settings: Settings, job_id: int | None) -> None:
    """Best-effort Telegram ping to the whitelisted user(s) when a job ends.

    Runs inside the app process (where the worker lives), posts straight to the
    Telegram HTTP API, and never raises — a broken bot must not break the queue.
    A per-job marker in ``app_settings`` keeps retries and parallel workers from
    sending twice.
    """
    if not job_id or not settings.telegram_bot_token or not settings.telegram_allowed_user_ids:
        return
    marker_key = f"telegram_notified:{job_id}"
    if session.get(AppSetting, marker_key) is not None:
        return
    job = session.get(Job, job_id)
    if job is None or job.status not in _TERMINAL:
        return

    text, video = _describe(session, job)
    delivered = False
    for user_id in settings.telegram_allowed_user_ids:
        delivered = _deliver(settings.telegram_bot_token, user_id, text, video) or delivered
    session.add(
        AppSetting(key=marker_key, value_json={"job_id": job_id, "status": job.status, "delivered": delivered})
    )
    session.flush()


def _describe(session: Session, job: Job) -> tuple[str, Path | None]:
    if job.status == JobStatus.FAILED.value:
        reason = job.error_message or "без деталей"
        return f"⚠️ Задача №{job.id} ({job.kind}) не удалась: {reason}", None

    if job.kind == JobKind.ANALYZE_EPISODE.value and job.episode_id is not None:
        episode = session.get(Episode, job.episode_id)
        count = (
            session.scalar(
                select(func.count()).select_from(ClipCandidate).where(ClipCandidate.episode_id == job.episode_id)
            )
            or 0
        )
        name = episode.file_name if episode else f"серия {job.episode_id}"
        return f"\U0001f3ac {name}: анализ завершён, кандидатов: {count}.\n/candidates {job.episode_id}", None

    if job.kind == JobKind.RENDER_CLIP.value:
        candidate_id = int((job.payload or {}).get("candidate_id", 0))
        candidate = session.get(ClipCandidate, candidate_id)
        export = session.scalars(
            select(Export).where(Export.candidate_id == candidate_id).order_by(Export.id.desc())
        ).first()
        title = candidate.title if candidate else f"кандидат {candidate_id}"
        return f"✅ Клип готов: {title}", _existing(export.output_path if export else None)

    if job.kind == JobKind.RENDER_STORY_ARC.value:
        arc_id = int((job.payload or {}).get("story_arc_id", 0))
        arc = session.get(StoryArc, arc_id)
        export = session.scalars(
            select(StoryArcExport).where(StoryArcExport.story_arc_id == arc_id).order_by(StoryArcExport.id.desc())
        ).first()
        title = arc.title if arc else f"арка {arc_id}"
        return f"✅ Сюжетное видео готово: {title}", _existing(export.output_path if export else None)

    return f"Задача №{job.id} завершена ({job.kind})", None


def _existing(path: str | None) -> Path | None:
    if not path:
        return None
    resolved = Path(path)
    return resolved if resolved.exists() else None


def _deliver(token: str, user_id: int, text: str, video: Path | None) -> bool:
    import httpx

    base = f"https://api.telegram.org/bot{token}"
    try:
        if video is not None and video.stat().st_size <= _VIDEO_LIMIT_BYTES:
            with video.open("rb") as handle:
                response = httpx.post(
                    f"{base}/sendVideo",
                    data={"chat_id": user_id, "caption": text[:1024]},
                    files={"video": handle},
                    timeout=180,
                )
        else:
            body = text if video is None else f"{text}\nФайл: {video}"
            response = httpx.post(
                f"{base}/sendMessage", data={"chat_id": user_id, "text": body[:4096]}, timeout=15
            )
        response.raise_for_status()
        return True
    except Exception:  # network, auth, file — never propagate
        logger.warning("Telegram notification failed for user %s", user_id, exc_info=True)
        return False
