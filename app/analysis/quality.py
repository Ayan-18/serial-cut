from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.schemas import CandidatePayload
from app.models.entities import ClipCandidate, Scene, TranscriptSegment, WordTimestamp


def calibrate_candidate(
    candidate: CandidatePayload,
    segments: list[TranscriptSegment],
    scenes: list[Scene],
    words: list[WordTimestamp],
) -> CandidatePayload:
    text = _range_text(segments, candidate.start_time, candidate.end_time)
    range_words = [word for word in words if candidate.start_time <= word.start_time <= candidate.end_time]
    range_scenes = [scene for scene in scenes if scene.end_time >= candidate.start_time and scene.start_time <= candidate.end_time]
    duration = max(0.1, candidate.end_time - candidate.start_time)

    boundary = 92 if text.rstrip().endswith((".", "!", "?", "…")) else 66
    opening = text[:180]
    hook = min(100, 68 + (10 if "?" in opening else 0) + (8 if "!" in opening else 0))
    word_density = len(range_words) / duration
    audio = 92 if 0.8 <= word_density <= 4.5 else 70
    scene_rate = len(range_scenes) / max(1.0, duration / 10)
    visual = min(96, max(58, round(64 + scene_rate * 7)))

    scores = candidate.scores.model_copy(
        update={
            "hook": round((candidate.scores.hook * 2 + hook) / 3),
            "boundary_quality": round((candidate.scores.boundary_quality + boundary) / 2),
            "visual_potential": round((candidate.scores.visual_potential * 2 + visual) / 3),
            "audio_quality": round((candidate.scores.audio_quality * 2 + audio) / 3),
        }
    )
    calibrated = round(
        scores.hook * 0.22
        + scores.standalone_context * 0.17
        + scores.payoff * 0.17
        + scores.emotion * 0.14
        + scores.boundary_quality * 0.12
        + scores.visual_potential * 0.10
        + scores.audio_quality * 0.08
    )
    problems = list(candidate.possible_problems)
    if boundary < 80 and len(problems) < 5:
        problems.append("Конец реплики может быть незавершённым")
    if audio < 80 and len(problems) < 5:
        problems.append("Проверьте паузы и плотность речи")
    return candidate.model_copy(update={"score": calibrated, "scores": scores, "possible_problems": problems})


def remove_cross_episode_duplicates(
    session: Session,
    episode_id: int,
    candidates: list[CandidatePayload],
    segments: list[TranscriptSegment],
    threshold: float = 0.84,
) -> list[CandidatePayload]:
    existing = session.scalars(select(ClipCandidate).where(ClipCandidate.episode_id != episode_id)).all()
    if not existing:
        return candidates
    segment_cache: dict[int, list[TranscriptSegment]] = {}
    result: list[CandidatePayload] = []
    for candidate in candidates:
        tokens = _tokens(_range_text(segments, candidate.start_time, candidate.end_time))
        duplicate = False
        for prior in existing:
            prior_segments = segment_cache.get(prior.episode_id)
            if prior_segments is None:
                prior_segments = session.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.episode_id == prior.episode_id)
                    .order_by(TranscriptSegment.start_time)
                ).all()
                segment_cache[prior.episode_id] = prior_segments
            prior_tokens = _tokens(_range_text(prior_segments, prior.start_time, prior.end_time))
            if prior.score >= candidate.score and _jaccard(tokens, prior_tokens) >= threshold:
                duplicate = True
                break
        if not duplicate:
            result.append(candidate)
    return result


def _range_text(segments: list[TranscriptSegment], start: float, end: float) -> str:
    return " ".join(item.text for item in segments if item.end_time >= start and item.start_time <= end).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[а-яёa-z0-9]+", text.casefold()) if len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
