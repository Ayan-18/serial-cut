from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analysis.text_similarity import natural_key, semantic_query_terms, semantic_similarity
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
    candidate_ids, transcript_ids = _indexed_document_ids(
        session,
        season_id,
        semantic_query_terms(query),
        max(limit * 8, 120),
    )
    candidate_query = select(ClipCandidate).where(ClipCandidate.episode_id.in_(list(episodes)))
    if candidate_ids is not None:
        if not candidate_ids:
            # Keep a small fuzzy fallback for spelling variations that FTS
            # prefix matching cannot see; the pool remains bounded.
            candidate_rows = session.scalars(candidate_query.order_by(ClipCandidate.score.desc()).limit(200)).all()
        else:
            candidate_rows = session.scalars(
                candidate_query.where(ClipCandidate.id.in_(candidate_ids)).order_by(ClipCandidate.score.desc())
            ).all()
    else:
        candidate_rows = session.scalars(candidate_query.order_by(ClipCandidate.score.desc()).limit(500)).all()
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

    transcript_query = select(TranscriptSegment).where(TranscriptSegment.episode_id.in_(list(episodes)))
    if transcript_ids is not None:
        if not transcript_ids:
            transcript_rows = session.scalars(
                transcript_query.order_by(TranscriptSegment.episode_id, TranscriptSegment.start_time).limit(300)
            ).all()
        else:
            transcript_rows = session.scalars(
                transcript_query.where(TranscriptSegment.id.in_(transcript_ids)).order_by(
                    TranscriptSegment.episode_id, TranscriptSegment.start_time
                )
            ).all()
    else:
        transcript_rows = session.scalars(
            transcript_query.order_by(TranscriptSegment.episode_id, TranscriptSegment.start_time).limit(1000)
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


def _indexed_document_ids(
    session: Session,
    season_id: int,
    roots: list[str],
    pool_limit: int,
) -> tuple[list[int] | None, list[int] | None]:
    if session.bind is None or session.bind.dialect.name != "sqlite" or not roots:
        return None, None
    try:
        _ensure_search_indexes(session)
        match_query = " OR ".join(f'"{item.replace(chr(34), "")}"*' for item in roots)
        candidate_ids = list(
            session.scalars(
                text(
                    "SELECT candidate_search.rowid FROM candidate_search "
                    "JOIN clip_candidates ON clip_candidates.id = candidate_search.rowid "
                    "JOIN episodes ON episodes.id = clip_candidates.episode_id "
                    "WHERE candidate_search MATCH :query AND episodes.season_id = :season_id "
                    "ORDER BY bm25(candidate_search) LIMIT :pool_limit"
                ),
                {"query": match_query, "season_id": season_id, "pool_limit": pool_limit},
            ).all()
        )
        transcript_ids = list(
            session.scalars(
                text(
                    "SELECT transcript_search.rowid FROM transcript_search "
                    "JOIN transcript_segments ON transcript_segments.id = transcript_search.rowid "
                    "JOIN episodes ON episodes.id = transcript_segments.episode_id "
                    "WHERE transcript_search MATCH :query AND episodes.season_id = :season_id "
                    "ORDER BY bm25(transcript_search) LIMIT :pool_limit"
                ),
                {"query": match_query, "season_id": season_id, "pool_limit": pool_limit},
            ).all()
        )
        return candidate_ids, transcript_ids
    except SQLAlchemyError:
        return None, None


def _ensure_search_indexes(session: Session) -> None:
    existing = {
        str(name)
        for name in session.scalars(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('candidate_search', 'transcript_search')"
            )
        ).all()
    }
    session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS transcript_search USING fts5("
            "text, content='transcript_segments', content_rowid='id', tokenize='unicode61')"
        )
    )
    session.execute(
        text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS candidate_search USING fts5("
            "title, description, moment_type, rationale, continuity_note, "
            "content='clip_candidates', content_rowid='id', tokenize='unicode61')"
        )
    )
    for statement in _SEARCH_TRIGGER_SQL:
        session.execute(text(statement))
    if "transcript_search" not in existing:
        session.execute(text("INSERT INTO transcript_search(transcript_search) VALUES('rebuild')"))
    if "candidate_search" not in existing:
        session.execute(text("INSERT INTO candidate_search(candidate_search) VALUES('rebuild')"))


_SEARCH_TRIGGER_SQL = (
    "CREATE TRIGGER IF NOT EXISTS transcript_search_ai AFTER INSERT ON transcript_segments BEGIN "
    "INSERT INTO transcript_search(rowid, text) VALUES (new.id, new.text); END",
    "CREATE TRIGGER IF NOT EXISTS transcript_search_ad AFTER DELETE ON transcript_segments BEGIN "
    "INSERT INTO transcript_search(transcript_search, rowid, text) VALUES ('delete', old.id, old.text); END",
    "CREATE TRIGGER IF NOT EXISTS transcript_search_au AFTER UPDATE ON transcript_segments BEGIN "
    "INSERT INTO transcript_search(transcript_search, rowid, text) VALUES ('delete', old.id, old.text); "
    "INSERT INTO transcript_search(rowid, text) VALUES (new.id, new.text); END",
    "CREATE TRIGGER IF NOT EXISTS candidate_search_ai AFTER INSERT ON clip_candidates BEGIN "
    "INSERT INTO candidate_search(rowid, title, description, moment_type, rationale, continuity_note) "
    "VALUES (new.id, new.title, new.description, new.moment_type, new.rationale, new.continuity_note); END",
    "CREATE TRIGGER IF NOT EXISTS candidate_search_ad AFTER DELETE ON clip_candidates BEGIN "
    "INSERT INTO candidate_search(candidate_search, rowid, title, description, moment_type, rationale, continuity_note) "
    "VALUES ('delete', old.id, old.title, old.description, old.moment_type, old.rationale, old.continuity_note); END",
    "CREATE TRIGGER IF NOT EXISTS candidate_search_au AFTER UPDATE ON clip_candidates BEGIN "
    "INSERT INTO candidate_search(candidate_search, rowid, title, description, moment_type, rationale, continuity_note) "
    "VALUES ('delete', old.id, old.title, old.description, old.moment_type, old.rationale, old.continuity_note); "
    "INSERT INTO candidate_search(rowid, title, description, moment_type, rationale, continuity_note) "
    "VALUES (new.id, new.title, new.description, new.moment_type, new.rationale, new.continuity_note); END",
)
