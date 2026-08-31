from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.text_similarity import natural_key, semantic_similarity
from app.models.entities import ClipCandidate, Episode, TranscriptSegment


@dataclass(frozen=True)
class SearchResult:
    kind: str
    episode_id: int
    episode_file_name: str
    candidate_id: int | None
    start_time: float
    end_time: float
    title: str
    snippet: str
    score: int


def search_season(session: Session, season_id: int, query: str, limit: int = 30) -> list[SearchResult]:
    terms = _terms(query)
    if not terms:
        return []
    episodes = {
        episode.id: episode
        for episode in session.scalars(select(Episode).where(Episode.season_id == season_id)).all()
    }
    if not episodes:
        return []

    results: list[SearchResult] = []
    candidate_rows = session.scalars(
        select(ClipCandidate).where(ClipCandidate.episode_id.in_(list(episodes))).order_by(ClipCandidate.score.desc())
    ).all()
    for candidate in candidate_rows:
        haystack = " ".join(
            [
                candidate.title,
                candidate.description,
                candidate.moment_type,
                candidate.rationale,
                candidate.continuity_note or "",
                episodes[candidate.episode_id].story_summary,
            ]
        )
        matches = _match_count(haystack, terms)
        semantic = semantic_similarity(query, haystack)
        if matches or semantic >= 0.10:
            episode = episodes[candidate.episode_id]
            results.append(
                SearchResult(
                    kind="candidate",
                    episode_id=episode.id,
                    episode_file_name=episode.file_name,
                    candidate_id=candidate.id,
                    start_time=candidate.start_time,
                    end_time=candidate.end_time,
                    title=candidate.title,
                    snippet=candidate.description,
                    score=min(100, round(candidate.score * 0.72 + matches * 4 + semantic * 32)),
                )
            )

    transcript_rows = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id.in_(list(episodes)))
        .order_by(TranscriptSegment.episode_id, TranscriptSegment.start_time)
    ).all()
    for row in transcript_rows:
        matches = _match_count(row.text, terms)
        semantic = semantic_similarity(query, row.text)
        if matches or semantic >= 0.16:
            episode = episodes[row.episode_id]
            results.append(
                SearchResult(
                    kind="transcript",
                    episode_id=episode.id,
                    episode_file_name=episode.file_name,
                    candidate_id=None,
                    start_time=row.start_time,
                    end_time=row.end_time,
                    title=row.speaker_label or "Реплика",
                    snippet=row.text,
                    score=min(100, round(48 + matches * 12 + semantic * 40)),
                )
            )
    return sorted(results, key=lambda item: (-item.score, natural_key(item.episode_file_name), item.start_time))[:limit]


def _terms(query: str) -> list[str]:
    return [item.strip(" ,.!?;:()[]{}«»\"'").lower() for item in query.split() if len(item.strip()) >= 3][:12]


def _match_count(value: str, terms: list[str]) -> int:
    text = value.lower()
    return sum(1 for term in terms if term in text)
