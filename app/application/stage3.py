from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analysis.llm import EpisodeAnalyzer, LlamaCppHttpAnalyzer, StubEpisodeAnalyzer
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates, transcript_text
from app.domain.enums import EpisodeStage
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, Episode, EpisodeOutline, Scene, TranscriptSegment, WordTimestamp


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

    outline = analyzer.outline(text)
    existing_outline = session.scalar(select(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    if existing_outline is None:
        session.add(EpisodeOutline(episode_id=episode_id, summary_json=outline.model_dump()))
    else:
        existing_outline.summary_json = outline.model_dump()
    episode.stage = EpisodeStage.OUTLINED.value
    session.flush()

    adjusted = []
    for candidate in analyzer.candidates(text, scenes).candidates:
        candidate = adjust_candidate_boundaries(
            candidate, words, scenes, settings.min_clip_seconds, settings.max_clip_seconds
        )
        if candidate is not None:
            adjusted.append(candidate)
    candidates = dedupe_candidates(adjusted)
    session.execute(delete(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
    for candidate in candidates:
        session.add(
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
            )
        )
    episode.stage = EpisodeStage.CANDIDATES_GENERATED.value
    session.flush()
    return Stage3Result(
        episode_id=episode_id,
        stage=episode.stage,
        outline_created=True,
        candidates=len(candidates),
    )


def _build_analyzer(settings: Settings) -> EpisodeAnalyzer:
    if settings.llm_adapter == "stub":
        return StubEpisodeAnalyzer()
    return LlamaCppHttpAnalyzer(settings.llm_base_url, settings.llm_model_hint)

