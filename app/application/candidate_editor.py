from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.media.subtitles import SubtitleCue, cues_for_range, cues_for_words
from app.models.entities import (
    CandidateSubtitle,
    ClipCandidate,
    TranscriptSegment,
    WordTimestamp,
)


@dataclass(frozen=True)
class EditableSubtitle:
    id: int | None
    start_time: float
    end_time: float
    text: str
    speaker_label: str | None = None


def subtitles_for_candidate(session: Session, candidate_id: int) -> list[EditableSubtitle]:
    candidate = _candidate(session, candidate_id)
    saved = session.scalars(
        select(CandidateSubtitle)
        .where(CandidateSubtitle.candidate_id == candidate_id)
        .order_by(CandidateSubtitle.sort_order, CandidateSubtitle.start_time)
    ).all()
    if saved:
        return [
            EditableSubtitle(row.id, row.start_time, row.end_time, row.text, row.speaker_label)
            for row in saved
        ]
    return generated_subtitles(session, candidate)


def generated_subtitles(session: Session, candidate: ClipCandidate) -> list[EditableSubtitle]:
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == candidate.episode_id)
        .order_by(TranscriptSegment.start_time)
    ).all()
    words = session.scalars(
        select(WordTimestamp)
        .join(TranscriptSegment, WordTimestamp.segment_id == TranscriptSegment.id)
        .where(TranscriptSegment.episode_id == candidate.episode_id)
        .order_by(WordTimestamp.start_time)
    ).all()
    cues = (
        cues_for_words(words, candidate.start_time, candidate.end_time)
        if words
        else cues_for_range(segments, candidate.start_time, candidate.end_time)
    )
    return [
        EditableSubtitle(
            None,
            cue.start_time,
            cue.end_time,
            cue.text.replace("\\N", "\n"),
            _speaker_for_cue(segments, candidate.start_time + cue.start_time),
        )
        for cue in cues
    ]


def save_candidate_subtitles(
    session: Session,
    candidate_id: int,
    subtitles: list[EditableSubtitle],
) -> list[EditableSubtitle]:
    candidate = _candidate(session, candidate_id)
    duration = candidate.end_time - candidate.start_time
    normalized = sorted(subtitles, key=lambda item: (item.start_time, item.end_time))
    previous_end = 0.0
    for item in normalized:
        if item.start_time < 0 or item.end_time <= item.start_time or item.end_time > duration + 0.05:
            raise ValueError("Тайминги субтитров должны находиться внутри границ кандидата")
        if item.start_time < previous_end - 0.05:
            raise ValueError("Субтитры не должны существенно перекрываться")
        if not item.text.strip():
            raise ValueError("Текст субтитров не может быть пустым")
        previous_end = item.end_time
    session.execute(delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate_id))
    for index, item in enumerate(normalized):
        session.add(
            CandidateSubtitle(
                candidate_id=candidate_id,
                start_time=round(item.start_time, 3),
                end_time=round(item.end_time, 3),
                text=item.text.strip().replace("\r\n", "\n"),
                speaker_label=item.speaker_label,
                sort_order=index,
            )
        )
    session.flush()
    return subtitles_for_candidate(session, candidate_id)


def reset_candidate_subtitles(session: Session, candidate_id: int) -> list[EditableSubtitle]:
    candidate = _candidate(session, candidate_id)
    session.execute(delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate_id))
    session.flush()
    return generated_subtitles(session, candidate)


def subtitle_cues_for_render(session: Session, candidate: ClipCandidate) -> list[SubtitleCue]:
    return [
        SubtitleCue(item.start_time, item.end_time, item.text.replace("\n", "\\N"))
        for item in subtitles_for_candidate(session, candidate.id)
    ]


def _candidate(session: Session, candidate_id: int) -> ClipCandidate:
    candidate = session.get(ClipCandidate, candidate_id)
    if candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found")
    return candidate


def _speaker_for_cue(segments: list[TranscriptSegment], absolute_start: float) -> str | None:
    for segment in segments:
        if segment.start_time - 0.1 <= absolute_start <= segment.end_time + 0.1:
            return segment.speaker_label
    return None
