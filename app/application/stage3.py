from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.llm import EpisodeAnalyzer, LlamaCppHttpAnalyzer, StubEpisodeAnalyzer
from app.analysis.quality import calibrate_candidate, remove_cross_episode_duplicates
from app.analysis.schemas import AnalysisContext
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates, transcript_text
from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    Episode,
    EpisodeOutline,
    ReviewDecision,
    Scene,
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
) -> Stage3Result:
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
    analyzer = analyzer or _build_analyzer(settings)
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

    outline = analyzer.outline(text, context)
    existing_outline = session.scalar(select(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    if existing_outline is None:
        session.add(EpisodeOutline(episode_id=episode_id, summary_json=outline.model_dump()))
    else:
        existing_outline.summary_json = outline.model_dump()
    episode.stage = EpisodeStage.OUTLINED.value
    session.commit()

    adjusted = []
    for candidate in analyzer.candidates(text, scenes, context, outline).candidates:
        candidate = adjust_candidate_boundaries(
            candidate, words, scenes, settings.min_clip_seconds, settings.max_clip_seconds, segments
        )
        if candidate is not None:
            adjusted.append(calibrate_candidate(candidate, segments, scenes, words))
    candidates = remove_cross_episode_duplicates(session, episode_id, dedupe_candidates(adjusted), segments)
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
                crop_mode="blurred-background",
                status="new",
                story_order=index if episode.candidate_mode == "story" else None,
                story_role=story_role,
                continuity_note=candidate.continuity_note,
            )
        )
    session.add_all(new_rows)
    session.flush()
    if previous_candidate_ids:
        session.execute(
            delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id.in_(previous_candidate_ids))
        )
        session.execute(
            delete(ReviewDecision).where(ReviewDecision.candidate_id.in_(previous_candidate_ids))
        )
        session.execute(delete(ClipCandidate).where(ClipCandidate.id.in_(previous_candidate_ids)))
    episode.stage = EpisodeStage.CANDIDATES_GENERATED.value
    session.commit()
    return Stage3Result(
        episode_id=episode_id,
        stage=episode.stage,
        outline_created=True,
        candidates=len(ordered_candidates),
    )


def _build_analyzer(settings: Settings) -> EpisodeAnalyzer:
    if settings.llm_adapter == "stub":
        return StubEpisodeAnalyzer()
    return LlamaCppHttpAnalyzer(settings.llm_base_url, settings.llm_model_hint)


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

