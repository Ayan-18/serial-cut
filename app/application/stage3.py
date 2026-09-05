from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.llm import EpisodeAnalyzer, LlamaCppHttpAnalyzer, StubEpisodeAnalyzer
from app.analysis.quality import calibrate_candidate, remove_cross_episode_duplicates
from app.analysis.schemas import AnalysisContext
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates, transcript_text
from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.infrastructure.processes import ProcessCancelledError
from app.application.derived_files import delete_derived_artifacts, delete_derived_tree
from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    Episode,
    EpisodeOutline,
    ReviewDecision,
    Scene,
    Export,
    StoryArc,
    StoryArcExport,
    StoryArcSegment,
    TranscriptSegment,
    WordTimestamp,
)


@dataclass(frozen=True)
class Stage3Result:
    episode_id: int
    stage: str
    outline_created: bool
    candidates: int


def run_stage3_candidate_analysis(
    session: Session,
    episode_id: int,
    settings: Settings,
    analyzer: EpisodeAnalyzer | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Stage3Result:
    _report(progress_callback, 0.02, "Загрузка расшифровки и сцен")
    _raise_if_cancelled(cancel_check)
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"Episode {episode_id} not found")
    segments = session.scalars(
        select(TranscriptSegment).where(TranscriptSegment.episode_id == episode_id).order_by(TranscriptSegment.start_time)
    ).all()
    if not segments:
        raise ValueError("Нет расшифровки: сначала выполните Stage 2")
    scenes = session.scalars(select(Scene).where(Scene.episode_id == episode_id).order_by(Scene.start_time)).all()
    words = session.scalars(
        select(WordTimestamp)
        .join(TranscriptSegment, WordTimestamp.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(WordTimestamp.start_time)
    ).all()
    analyzer = analyzer or _build_analyzer(
        settings,
        progress_callback=lambda value, message: _report(
            progress_callback, 0.28 + value * 0.48, message
        ),
        cancel_check=cancel_check,
    )
    text = transcript_text(segments)
    context = AnalysisContext(
        season_summary=episode.season.story_context,
        episode_summary=episode.story_summary,
        required_events=list(episode.required_events_json or []),
        excluded_events=list(episode.excluded_events_json or []),
        spoilers_allowed=episode.spoilers_allowed,
        candidate_mode=episode.candidate_mode,
    )
    session.commit()

    _report(progress_callback, 0.12, "Построение карты серии")
    outline = analyzer.outline(text, context)
    _raise_if_cancelled(cancel_check)
    existing_outline = session.scalar(select(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    if existing_outline is None:
        session.add(EpisodeOutline(episode_id=episode_id, summary_json=outline.model_dump()))
    else:
        existing_outline.summary_json = outline.model_dump()
    episode.stage = EpisodeStage.OUTLINED.value
    session.commit()

    _report(progress_callback, 0.28, "Поиск сюжетных кандидатов")
    generated = analyzer.candidates(text, scenes, context, outline).candidates
    _raise_if_cancelled(cancel_check)
    adjusted = []
    for index, candidate in enumerate(generated, start=1):
        _raise_if_cancelled(cancel_check)
        candidate = adjust_candidate_boundaries(
            candidate, words, scenes, settings.min_clip_seconds, settings.max_clip_seconds, segments
        )
        if candidate is not None:
            adjusted.append(calibrate_candidate(candidate, segments, scenes, words))
        _report(
            progress_callback,
            0.76 + 0.12 * index / max(1, len(generated)),
            f"Проверка границ: {index} из {len(generated)}",
        )
    candidates = remove_cross_episode_duplicates(session, episode_id, dedupe_candidates(adjusted), segments)
    _report(progress_callback, 0.90, "Сохранение проверенных кандидатов")
    previous_candidate_ids = list(
        session.scalars(select(ClipCandidate.id).where(ClipCandidate.episode_id == episode_id)).all()
    )
    ordered_candidates = sorted(candidates, key=lambda item: item.start_time)
    new_rows: list[ClipCandidate] = []
    for index, candidate in enumerate(ordered_candidates, start=1):
        story_role = candidate.story_role
        if episode.candidate_mode == "story" and not story_role:
            story_role = _default_story_role(index, len(ordered_candidates))
        new_rows.append(
            ClipCandidate(
                episode_id=episode_id,
                start_time=candidate.start_time,
                end_time=candidate.end_time,
                title=candidate.title,
                description=candidate.description,
                moment_type=candidate.moment_type,
                score=candidate.score,
                scores_json=candidate.scores.model_dump(),
                rationale=candidate.standalone_reason,
                problems_json=candidate.possible_problems,
                crop_mode="center-crop",
                status="new",
                story_order=index if episode.candidate_mode == "story" else None,
                story_role=story_role,
                continuity_note=candidate.continuity_note,
            )
        )
    session.add_all(new_rows)
    session.flush()
    obsolete_artifacts: list[str | None] = []
    if previous_candidate_ids:
        previous_exports = session.scalars(
            select(Export).where(Export.candidate_id.in_(previous_candidate_ids))
        ).all()
        for item in previous_exports:
            obsolete_artifacts.extend(
                [item.output_path, item.metadata_path, item.subtitle_path, item.cover_path]
            )
        linked_segments = session.scalars(
            select(StoryArcSegment).where(StoryArcSegment.candidate_id.in_(previous_candidate_ids))
        ).all()
        affected_arc_ids: set[int] = set()
        for segment in linked_segments:
            affected_arc_ids.add(segment.story_arc_id)
            segment.note = (segment.note + " · " if segment.note else "") + "Кандидат пересоздан; оставлен снимок границ"
            segment.candidate_id = None
            segment.candidate_revision = 0
            segment.manually_edited = True
        for arc_id in affected_arc_ids:
            arc = session.get(StoryArc, arc_id)
            if arc is not None:
                arc.status = "draft"
                arc.edit_revision += 1
            for export in session.scalars(
                select(StoryArcExport).where(StoryArcExport.story_arc_id == arc_id)
            ).all():
                export.status = "stale"
        # Persist the candidate_id=NULL snapshots before deleting the replaced
        # candidates. This ordering matters when SQLite foreign keys are on.
        session.flush()
        session.execute(
            delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id.in_(previous_candidate_ids))
        )
        session.execute(
            delete(ReviewDecision).where(ReviewDecision.candidate_id.in_(previous_candidate_ids))
        )
        session.execute(delete(Export).where(Export.candidate_id.in_(previous_candidate_ids)))
        session.execute(delete(ClipCandidate).where(ClipCandidate.id.in_(previous_candidate_ids)))
    episode.stage = EpisodeStage.CANDIDATES_GENERATED.value
    session.commit()
    delete_derived_artifacts(obsolete_artifacts, [settings.output_dir, settings.cache_dir])
    delete_derived_tree(
        settings.cache_dir / "previews" / episode.fingerprint,
        [settings.cache_dir],
    )
    _report(progress_callback, 1.0, "Кандидаты готовы")
    return Stage3Result(
        episode_id=episode_id,
        stage=episode.stage,
        outline_created=True,
        candidates=len(ordered_candidates),
    )


def _build_analyzer(
    settings: Settings,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> EpisodeAnalyzer:
    if settings.llm_adapter == "stub":
        return StubEpisodeAnalyzer()
    return LlamaCppHttpAnalyzer(
        settings.llm_base_url,
        settings.llm_model_hint,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def _report(callback: Callable[[float, str], None] | None, value: float, message: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, value)), message)


def _raise_if_cancelled(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProcessCancelledError("Анализ кандидатов остановлен пользователем")


def _default_story_role(index: int, count: int) -> str:
    if index == 1:
        return "завязка"
    if index == count:
        return "итог"
    ratio = index / max(1, count)
    if ratio <= 0.4:
        return "развитие"
    if ratio <= 0.65:
        return "конфликт"
    if ratio <= 0.85:
        return "поворот"
    return "кульминация"

