from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    CharacterRead,
    PublishingPlanRead,
    SpeakerIdentityRead,
    StoryArcExportRead,
    StoryArcRead,
    StoryArcSegmentRead,
    StoryContextRead,
    VideoScriptRead,
)
from app.application.processing_guard import ProcessingBusyError
from app.domain.enums import JobStatus
from app.infrastructure.config import get_settings
from app.models.entities import (
    Character,
    ClipCandidate,
    Episode,
    Export,
    Job,
    PublishingPlan,
    Season,
    SpeakerIdentity,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    VideoScript,
)

logger = logging.getLogger(__name__)


def _get_export(session: Session, export_id: int) -> Export:
    export = session.get(Export, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Экспорт не найден")
    return export


def _get_story_arc_export(session: Session, export_id: int) -> StoryArcExport:
    export = session.get(StoryArcExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="StoryArc export не найден")
    return export


def _get_episode(session: Session, episode_id: int) -> Episode:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Серия не найдена")
    return episode


def _story_context_read(episode: Episode) -> StoryContextRead:
    return StoryContextRead(
        season_id=episode.season_id,
        episode_id=episode.id,
        season_context=episode.season.story_context,
        episode_summary=episode.story_summary,
        required_events=list(episode.required_events_json or []),
        excluded_events=list(episode.excluded_events_json or []),
        spoilers_allowed=episode.spoilers_allowed,
        candidate_mode=episode.candidate_mode,
    )


def _story_arc_read(session: Session, arc: StoryArc) -> StoryArcRead:
    season = session.get(Season, arc.season_id)
    character = session.get(Character, arc.target_character_id) if arc.target_character_id else None
    return StoryArcRead(
        id=arc.id,
        season_id=arc.season_id,
        season_title=season.title if season else "",
        title=arc.title,
        prompt=arc.prompt,
        arc_type=arc.arc_type,
        output_format=arc.output_format,
        target_character_id=arc.target_character_id,
        target_character_name=character.name if character else None,
        status=arc.status,
        total_duration_seconds=arc.total_duration_seconds,
        plan_json=arc.plan_json,
        segments=[_story_arc_segment_read(session, item) for item in arc.segments],
        exports=[_story_arc_export_read(item) for item in sorted(arc.exports, key=lambda export: export.id, reverse=True)],
    )


def _story_arc_segment_read(session: Session, segment: StoryArcSegment) -> StoryArcSegmentRead:
    episode = session.get(Episode, segment.episode_id)
    candidate = session.get(ClipCandidate, segment.candidate_id) if segment.candidate_id else None
    return StoryArcSegmentRead(
        id=segment.id,
        story_arc_id=segment.story_arc_id,
        episode_id=segment.episode_id,
        episode_file_name=episode.file_name if episode else "",
        candidate_id=segment.candidate_id,
        candidate_score=candidate.score if candidate else None,
        sort_order=segment.sort_order,
        start_time=segment.start_time,
        end_time=segment.end_time,
        title=segment.title,
        note=segment.note,
        role=segment.role,
    )


def _story_arc_export_read(export: StoryArcExport) -> StoryArcExportRead:
    return StoryArcExportRead(
        id=export.id,
        story_arc_id=export.story_arc_id,
        output_path=export.output_path,
        metadata_path=export.metadata_path,
        cover_path=export.cover_path,
        width=export.width,
        height=export.height,
        include_subtitles=export.include_subtitles,
        preset_name=export.preset_name,
        segment_count=export.segment_count,
        status=export.status,
        transition_style=export.transition_style,
        narration_included=export.narration_included,
        version=export.version,
        render_fingerprint=export.render_fingerprint,
    )


def _video_script_read(script: VideoScript) -> VideoScriptRead:
    return VideoScriptRead(
        id=script.id,
        season_id=script.season_id,
        story_arc_id=script.story_arc_id,
        title=script.title,
        prompt=script.prompt,
        style=script.style,
        script_text=script.script_text,
        structure_json=script.structure_json,
        status=script.status,
    )


def _publishing_plan_read(plan: PublishingPlan) -> PublishingPlanRead:
    return PublishingPlanRead(
        id=plan.id,
        season_id=plan.season_id,
        story_arc_id=plan.story_arc_id,
        story_arc_export_id=plan.story_arc_export_id,
        platform=plan.platform,
        title=plan.title,
        description=plan.description,
        hashtags=list(plan.hashtags_json or []),
        scheduled_for=plan.scheduled_for,
        status=plan.status,
    )


def _character_read(character: Character) -> CharacterRead:
    from app.application.narration_voice import auto_voice_for_character

    photos = list(character.photos_json or [])
    return CharacterRead(
        id=character.id,
        season_id=character.season_id,
        name=character.name,
        description=character.description,
        aliases=list(character.aliases_json or []),
        color=character.color,
        photo_count=len(photos),
        photo_urls=[f"/api/characters/{character.id}/photos/{index}" for index in range(len(photos))],
        voice_sample_count=int((character.voice_profile_json or {}).get("sample_count", 0)),
        narration_voice=character.narration_voice,
        narration_voice_auto=auto_voice_for_character(character, get_settings().tts_narrator_voice),
    )


def _speaker_identity_read(session: Session, identity: SpeakerIdentity) -> SpeakerIdentityRead:
    character = session.get(Character, identity.character_id)
    if character is None:
        raise HTTPException(status_code=409, detail="Привязанный персонаж не найден")
    return SpeakerIdentityRead(
        source_label=identity.source_label,
        character_id=character.id,
        character_name=character.name,
        confidence=identity.confidence,
        method=identity.method,
    )


def _ensure_episode_not_enqueued(session: Session, episode_id: int) -> None:
    active_job_id = session.scalar(
        select(Job.id).where(
            Job.episode_id == episode_id,
            Job.status.in_(
                [
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.PAUSED.value,
                    JobStatus.CANCEL_REQUESTED.value,
                ]
            ),
        ).limit(1)
    )
    if active_job_id is not None:
        raise ProcessingBusyError(
            f"Серия уже обрабатывается задачей №{active_job_id}. Используйте управление очередью."
        )


def _ensure_no_active_jobs(session: Session, message: str) -> None:
    active_job_id = session.scalar(
        select(Job.id)
        .where(
            Job.status.in_(
                [
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                    JobStatus.PAUSED.value,
                    JobStatus.CANCEL_REQUESTED.value,
                ]
            )
        )
        .limit(1)
    )
    if active_job_id is not None:
        raise ProcessingBusyError(f"{message}. Задача №{active_job_id} ещё не завершена.")


def _cache_protected_paths(session: Session, output_dir: Path) -> list[Path]:
    paths = [Path(__file__).resolve().parents[2], output_dir]
    paths.extend(Path(item) for item in session.scalars(select(Season.root_path)).all())
    paths.extend(Path(item) for item in session.scalars(select(Episode.file_path)).all())
    return paths


def _is_legacy_default_cache(cache_dir: Path) -> bool:
    default_cache = Path(__file__).resolve().parents[2] / "data" / "cache"
    return cache_dir.expanduser().resolve(strict=False) == default_cache.resolve(strict=False)



