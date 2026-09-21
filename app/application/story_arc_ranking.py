from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.text_similarity import natural_key, semantic_similarity
from app.models.entities import (
    Character,
    ClipCandidate,
    Episode,
    SpeakerIdentity,
    TranscriptSegment,
)


@dataclass(frozen=True)
class StoryArcPlanRequest:
    season_id: int
    title: str | None = None
    prompt: str = ""
    arc_type: str = "custom"
    output_format: str = "shorts_series"
    target_character_id: int | None = None
    max_segments: int = 8
    max_duration_seconds: int = 420


@dataclass(frozen=True)
class StoryArcBuildItem:
    candidate: ClipCandidate
    episode: Episode
    score: float
    reason: str


def _rank_candidates(
    session: Session,
    season_id: int,
    prompt: str,
    character: Character | None,
) -> list[StoryArcBuildItem]:
    rows = session.execute(
        select(ClipCandidate, Episode)
        .join(Episode, Episode.id == ClipCandidate.episode_id)
        .where(Episode.season_id == season_id)
        .where(ClipCandidate.status != "rejected")
        .order_by(Episode.file_name, ClipCandidate.start_time)
    ).all()
    speaker_labels = _character_speaker_labels(session, season_id, character.id) if character else {}
    prompt_terms = _terms(prompt)
    items: list[StoryArcBuildItem] = []
    for candidate, episode in rows:
        text = " ".join(
            [
                candidate.title,
                candidate.description,
                candidate.moment_type,
                candidate.rationale,
                candidate.continuity_note or "",
                episode.story_summary,
            ]
        )
        score = float(candidate.score)
        reasons: list[str] = [f"score {candidate.score}"]
        if candidate.story_order is not None:
            score += 5
            reasons.append("есть роль в сюжетном режиме")
        if prompt_terms:
            matches = sum(1 for term in prompt_terms if term in text.lower())
            semantic = semantic_similarity(prompt, text)
            if matches:
                score += min(20, matches * 5)
                reasons.append(f"совпадений с запросом: {matches}")
            if semantic >= 0.18:
                score += min(18, round(semantic * 30))
                reasons.append(f"смысловая близость: {round(semantic * 100)}%")
        labels = speaker_labels.get(episode.id, set())
        if labels and _candidate_has_speaker(session, candidate, labels):
            score += 18
            reasons.append(f"есть реплики персонажа {character.name if character else ''}".strip())
        duration = candidate.end_time - candidate.start_time
        if duration < 12:
            score -= 8
            reasons.append("очень короткий кусок")
        if candidate.problems_json:
            score -= min(12, len(candidate.problems_json) * 3)
            reasons.append("есть замечания к кандидату")
        if candidate.status in {"approved", "rendered"}:
            score += 5
            reasons.append("подтверждено пользователем")
        items.append(StoryArcBuildItem(candidate, episode, score, ", ".join(reasons)))
    return sorted(items, key=lambda item: item.score, reverse=True)


def _select_arc_items(
    candidates: list[StoryArcBuildItem],
    max_segments: int,
    max_duration_seconds: int,
) -> list[StoryArcBuildItem]:
    if max_segments <= 0 or max_duration_seconds <= 0:
        return []
    selected: list[StoryArcBuildItem] = []
    per_episode: dict[int, int] = {}
    total = 0.0
    for item in candidates:
        duration = item.candidate.end_time - item.candidate.start_time
        if len(selected) >= max_segments:
            break
        if total + duration > max_duration_seconds and selected:
            continue
        if per_episode.get(item.episode.id, 0) >= 2 and len(selected) < min(max_segments, 4):
            continue
        if any(
            item.episode.id == kept.episode.id
            and _candidate_similarity(item.candidate, kept.candidate) >= 0.82
            for kept in selected
        ):
            continue
        selected.append(item)
        per_episode[item.episode.id] = per_episode.get(item.episode.id, 0) + 1
        total += duration
    return sorted(selected, key=lambda item: (natural_key(item.episode.file_name), item.candidate.start_time))


def _character_speaker_labels(session: Session, season_id: int, character_id: int) -> dict[int, set[str]]:
    rows = session.execute(
        select(SpeakerIdentity.episode_id, SpeakerIdentity.source_label)
        .join(Episode, Episode.id == SpeakerIdentity.episode_id)
        .where(Episode.season_id == season_id)
        .where(SpeakerIdentity.character_id == character_id)
    ).all()
    result: dict[int, set[str]] = {}
    for episode_id, label in rows:
        result.setdefault(episode_id, set()).add(label)
    return result


def _candidate_has_speaker(session: Session, candidate: ClipCandidate, labels: set[str]) -> bool:
    if not labels:
        return False
    return session.scalar(
        select(TranscriptSegment.id)
        .where(TranscriptSegment.episode_id == candidate.episode_id)
        .where(TranscriptSegment.speaker_label.in_(labels))
        .where(TranscriptSegment.end_time >= candidate.start_time)
        .where(TranscriptSegment.start_time <= candidate.end_time)
        .limit(1)
    ) is not None


def _terms(prompt: str) -> list[str]:
    terms = [item.strip(" ,.!?;:()[]{}«»\"'").lower() for item in prompt.split()]
    return [item for item in terms if len(item) >= 4][:12]


def _candidate_similarity(left: ClipCandidate, right: ClipCandidate) -> float:
    left_text = " ".join([left.title, left.description, left.continuity_note or ""])
    right_text = " ".join([right.title, right.description, right.continuity_note or ""])
    return semantic_similarity(left_text, right_text)
