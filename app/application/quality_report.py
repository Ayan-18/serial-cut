from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import ClipCandidate, Episode, Scene, TranscriptSegment, WordTimestamp


@dataclass(frozen=True)
class CandidateQualityReport:
    candidate_id: int
    duration_seconds: float
    final_score: int
    boundary_score: int
    standalone_score: int
    payoff_score: int
    audio_score: int
    visual_score: int
    problems: list[str]
    recommendations: list[str]


@dataclass(frozen=True)
class EpisodeQualityReport:
    episode_id: int
    stage: str
    transcript_segments: int
    words: int
    scenes: int
    candidates: int
    approved: int
    rejected: int
    rendered: int
    average_score: int
    problem_candidates: int
    top_problems: list[str]
    media_warnings: list[str]


def candidate_quality_report(session: Session, candidate_id: int) -> CandidateQualityReport:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    scores = candidate.scores_json or {}
    duration = max(0.0, candidate.end_time - candidate.start_time)
    problems = list(candidate.problems_json or [])
    recommendations = _candidate_recommendations(candidate, scores, duration, problems)
    return CandidateQualityReport(
        candidate_id=candidate.id,
        duration_seconds=round(duration, 2),
        final_score=candidate.score,
        boundary_score=int(scores.get("boundary_quality", candidate.score)),
        standalone_score=int(scores.get("standalone_context", candidate.score)),
        payoff_score=int(scores.get("payoff", candidate.score)),
        audio_score=int(scores.get("audio_quality", candidate.score)),
        visual_score=int(scores.get("visual_potential", candidate.score)),
        problems=problems,
        recommendations=recommendations,
    )


def episode_quality_report(session: Session, episode_id: int) -> EpisodeQualityReport:
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"Episode {episode_id} not found")
    candidates = session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id == episode_id)
    ).all()
    segment_count = session.scalar(
        select(func.count(TranscriptSegment.id)).where(TranscriptSegment.episode_id == episode_id)
    )
    word_count = _word_count(session, episode_id)
    scene_count = len(session.scalars(select(Scene).where(Scene.episode_id == episode_id)).all())
    scores = [candidate.score for candidate in candidates]
    problems: list[str] = []
    for candidate in candidates:
        problems.extend(str(item) for item in candidate.problems_json or [])
    return EpisodeQualityReport(
        episode_id=episode.id,
        stage=episode.stage,
        transcript_segments=int(segment_count),
        words=word_count,
        scenes=scene_count,
        candidates=len(candidates),
        approved=sum(candidate.status == "approved" for candidate in candidates),
        rejected=sum(candidate.status == "rejected" for candidate in candidates),
        rendered=sum(candidate.status == "rendered" for candidate in candidates),
        average_score=round(sum(scores) / len(scores)) if scores else 0,
        problem_candidates=sum(1 for candidate in candidates if candidate.problems_json),
        top_problems=_top_items(problems),
        media_warnings=[
            str(item.get("message") or item.get("code") or "")
            for item in (episode.probe_json or {}).get("serialcuts_warnings") or []
            if item.get("message") or item.get("code")
        ],
    )


def _word_count(session: Session, episode_id: int) -> int:
    segments = session.scalars(
        select(TranscriptSegment.id).where(TranscriptSegment.episode_id == episode_id)
    ).all()
    if not segments:
        return 0
    return len(
        session.scalars(select(WordTimestamp).where(WordTimestamp.segment_id.in_(segments))).all()
    )


def _candidate_recommendations(
    candidate: ClipCandidate,
    scores: dict,
    duration: float,
    problems: list[str],
) -> list[str]:
    recommendations: list[str] = []
    if int(scores.get("boundary_quality", 100)) < 78:
        recommendations.append("Проверьте начало и конец: возможно, клип режет реплику.")
    if int(scores.get("standalone_context", 100)) < 72:
        recommendations.append("Добавьте предыдущую реплику или короткий контекст перед моментом.")
    if int(scores.get("payoff", 100)) < 72:
        recommendations.append("Сдвиньте конец к более сильной финальной реплике.")
    if int(scores.get("visual_potential", 100)) < 70:
        recommendations.append("Проверьте кадрирование и активного персонажа в предпросмотре.")
    if int(scores.get("audio_quality", 100)) < 75:
        recommendations.append("Проверьте длинные паузы, тишину и плотность речи.")
    if duration < 25:
        recommendations.append("Клип слишком короткий для самостоятельной сцены.")
    if duration > 59:
        recommendations.append("Клип длиннее формата Shorts/Reels, лучше сузить границы.")
    if any("похож" in problem.casefold() for problem in problems):
        recommendations.append("Сравните с соседними кандидатами и оставьте более сильный дубль.")
    if candidate.crop_mode == "center-crop":
        recommendations.append("Для диалога попробуйте кадрирование «По лицу».")
    return _unique(recommendations[:6])


def _top_items(items: list[str], limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return [
        item for item, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
