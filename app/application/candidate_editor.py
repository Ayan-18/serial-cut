from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.application.speaker_names import speaker_name_map
from app.media.subtitles import SubtitleCue, cues_for_range, cues_for_words, wrap_russian_subtitle
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


@dataclass(frozen=True)
class SubtitleQualityReport:
    candidate_id: int
    rows: int
    warnings: list[str]
    long_rows: int
    overlaps: int
    too_fast_rows: int


def subtitles_for_candidate(session: Session, candidate_id: int) -> list[EditableSubtitle]:
    candidate = _candidate(session, candidate_id)
    identities = speaker_name_map(session, candidate.episode_id)
    saved = session.scalars(
        select(CandidateSubtitle)
        .where(CandidateSubtitle.candidate_id == candidate_id)
        .order_by(CandidateSubtitle.sort_order, CandidateSubtitle.start_time)
    ).all()
    if saved:
        return [
            EditableSubtitle(
                row.id,
                row.start_time,
                row.end_time,
                row.text,
                identities.get(row.speaker_label, row.speaker_label),
            )
            for row in saved
        ]
    return generated_subtitles(session, candidate)


def generated_subtitles(session: Session, candidate: ClipCandidate) -> list[EditableSubtitle]:
    identities = speaker_name_map(session, candidate.episode_id)
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
            _resolved_speaker_for_cue(segments, candidate.start_time + cue.start_time, identities),
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


def subtitle_quality_report(session: Session, candidate_id: int) -> SubtitleQualityReport:
    subtitles = subtitles_for_candidate(session, candidate_id)
    warnings: list[str] = []
    long_rows = 0
    overlaps = 0
    too_fast_rows = 0
    previous_end = 0.0
    for index, subtitle in enumerate(subtitles, start=1):
        text = subtitle.text.replace("\n", " ").strip()
        duration = max(0.1, subtitle.end_time - subtitle.start_time)
        if len(text) > 76 or any(len(line) > 38 for line in subtitle.text.splitlines()):
            long_rows += 1
            warnings.append(f"Строка {index}: длинный текст, лучше разбить")
        if subtitle.start_time < previous_end - 0.05:
            overlaps += 1
            warnings.append(f"Строка {index}: пересекается с предыдущей")
        if len(text) / duration > 24:
            too_fast_rows += 1
            warnings.append(f"Строка {index}: слишком быстро читается")
        previous_end = max(previous_end, subtitle.end_time)
    return SubtitleQualityReport(
        candidate_id=candidate_id,
        rows=len(subtitles),
        warnings=_unique(warnings),
        long_rows=long_rows,
        overlaps=overlaps,
        too_fast_rows=too_fast_rows,
    )


def auto_split_candidate_subtitles(
    session: Session,
    candidate_id: int,
    max_chars_per_line: int = 32,
) -> list[EditableSubtitle]:
    current = subtitles_for_candidate(session, candidate_id)
    split_rows: list[EditableSubtitle] = []
    for row in current:
        pages = [page.replace("\\N", "\n") for page in wrap_russian_subtitle(row.text, max_chars_per_line)]
        if len(pages) <= 1:
            split_rows.append(row)
            continue
        duration = row.end_time - row.start_time
        weights = [max(1, len(page.replace("\n", " ").split())) for page in pages]
        total = sum(weights)
        elapsed = 0
        for page, weight in zip(pages, weights, strict=True):
            start = row.start_time + duration * elapsed / total
            elapsed += weight
            end = row.start_time + duration * elapsed / total
            split_rows.append(
                EditableSubtitle(
                    None,
                    round(start, 3),
                    round(max(start + 0.25, end), 3),
                    page,
                    row.speaker_label,
                )
            )
    return save_candidate_subtitles(session, candidate_id, split_rows)


def reset_candidate_subtitles(session: Session, candidate_id: int) -> list[EditableSubtitle]:
    candidate = _candidate(session, candidate_id)
    session.execute(delete(CandidateSubtitle).where(CandidateSubtitle.candidate_id == candidate_id))
    session.flush()
    return generated_subtitles(session, candidate)


def subtitle_cues_for_render(
    session: Session,
    candidate: ClipCandidate,
    show_speaker_names: bool = False,
) -> list[SubtitleCue]:
    return [
        SubtitleCue(
            item.start_time,
            item.end_time,
            _subtitle_render_text(item, show_speaker_names),
        )
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


def _resolved_speaker_for_cue(
    segments: list[TranscriptSegment],
    absolute_start: float,
    identities: dict[str, str],
) -> str | None:
    label = _speaker_for_cue(segments, absolute_start)
    return identities.get(label, label)


def _subtitle_render_text(item: EditableSubtitle, show_speaker_names: bool) -> str:
    text = item.text.replace("\n", "\\N")
    if not show_speaker_names or not item.speaker_label:
        return text
    safe_label = item.speaker_label.replace("{", "").replace("}", "").replace("\\", "").strip()
    return f"{{\\b1}}{safe_label}:{{\\b0}}\\N{text}" if safe_label else text


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
