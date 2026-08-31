from __future__ import annotations

from app.analysis.schemas import CandidatePayload
from app.models.entities import Scene, TranscriptSegment, WordTimestamp


def adjust_candidate_boundaries(
    candidate: CandidatePayload,
    words: list[WordTimestamp],
    scenes: list[Scene],
    min_seconds: int,
    max_seconds: int,
    segments: list[TranscriptSegment] | None = None,
) -> CandidatePayload | None:
    start = max(0.0, candidate.start_time)
    end = candidate.end_time
    nearby_words = [word for word in words if word.end_time >= start - 2 and word.start_time <= end + 2]
    spoken_words = [word for word in nearby_words if word.start_time >= start and word.end_time <= end]
    if spoken_words:
        start = max(0.0, min(start, spoken_words[0].start_time - 0.35))
        end = max(end, spoken_words[-1].end_time + 0.55)

    if segments:
        overlapping = [segment for segment in segments if segment.end_time >= start and segment.start_time <= end]
        if overlapping:
            if abs(overlapping[0].start_time - start) <= 1.5:
                start = max(0.0, overlapping[0].start_time)
            if abs(overlapping[-1].end_time - end) <= 2.0:
                end = overlapping[-1].end_time

    start, end = _snap_to_scene_edges(start, end, scenes)
    duration = end - start
    if duration < min_seconds:
        episode_end = max((scene.end_time for scene in scenes), default=start + min_seconds)
        end = min(start + min_seconds, episode_end)
        if end - start < min_seconds:
            start = max(0.0, end - min_seconds)
        start, end = _snap_to_scene_edges(start, end, scenes)
    if segments:
        start, end = _fit_complete_speech(start, end, segments, min_seconds, max_seconds)
        start, end = _optimize_semantic_window(start, end, segments, min_seconds, max_seconds)
    elif end - start > max_seconds:
        end = start + max_seconds
    if end <= start or end - start < min_seconds:
        return None
    return candidate.model_copy(update={"start_time": round(start, 3), "end_time": round(end, 3)})


def _fit_complete_speech(
    start: float,
    end: float,
    segments: list[TranscriptSegment],
    min_seconds: int,
    max_seconds: int,
) -> tuple[float, float]:
    ordered = sorted(segments, key=lambda item: item.start_time)
    crossing_start = next(
        (item for item in ordered if item.start_time + 0.05 < start < item.end_time - 0.05),
        None,
    )
    if crossing_start is not None:
        if start - crossing_start.start_time <= 1.5 and end - crossing_start.start_time <= max_seconds:
            start = crossing_start.start_time
        else:
            start = crossing_start.end_time

    crossing_end = next(
        (item for item in ordered if item.start_time + 0.05 < end < item.end_time - 0.05),
        None,
    )
    if crossing_end is not None:
        if crossing_end.end_time - start <= max_seconds:
            end = crossing_end.end_time
        else:
            end = crossing_end.start_time

    if end - start > max_seconds:
        hard_end = start + max_seconds
        safe_ends = [
            item.end_time
            for item in ordered
            if start < item.end_time <= hard_end and item.end_time - start >= min_seconds
        ]
        end = max(safe_ends) if safe_ends else hard_end

    return start, end


def _optimize_semantic_window(
    start: float,
    end: float,
    segments: list[TranscriptSegment],
    min_seconds: int,
    max_seconds: int,
) -> tuple[float, float]:
    ordered = sorted(segments, key=lambda item: item.start_time)
    selected = [item for item in ordered if item.end_time > start and item.start_time < end]
    if not selected:
        return start, end

    start, end = _trim_weak_edges(start, end, selected, min_seconds)

    first_index = ordered.index(selected[0])
    previous = ordered[first_index - 1] if first_index > 0 else None
    if (
        previous is not None
        and 0 <= start - previous.end_time <= 1.2
        and not _is_recap_or_credits(previous.text)
        and not _is_weak_opening(previous.text)
        and end - previous.start_time <= max_seconds
    ):
        start = previous.start_time

    selected = [item for item in ordered if item.end_time > start and item.start_time < end]
    if end - start > max_seconds or not _has_strong_ending(selected):
        hard_end = start + max_seconds
        safe_segments = [
            item
            for item in ordered
            if item.end_time <= hard_end and item.end_time - start >= min_seconds and item.end_time > start
        ]
        strong_ends = [
            item.end_time
            for item in safe_segments
            if _has_payoff_marker(item.text) or _has_terminal_punctuation(item.text)
        ]
        if strong_ends:
            end = max(strong_ends)
        elif safe_segments:
            end = safe_segments[-1].end_time
        else:
            end = min(end, hard_end)

    if end - start < min_seconds:
        later = [
            item.end_time
            for item in ordered
            if item.end_time > end and item.end_time - start <= max_seconds and item.end_time - start >= min_seconds
        ]
        if later:
            end = later[0]
    return start, min(end, start + max_seconds)


def _trim_weak_edges(
    start: float,
    end: float,
    selected: list[TranscriptSegment],
    min_seconds: int,
) -> tuple[float, float]:
    while len(selected) > 1 and _is_weak_opening(selected[0].text):
        candidate_start = selected[1].start_time
        if end - candidate_start < min_seconds:
            break
        start = candidate_start
        selected = selected[1:]
    while len(selected) > 1 and _is_recap_or_credits(selected[-1].text):
        candidate_end = selected[-2].end_time
        if candidate_end - start < min_seconds:
            break
        end = candidate_end
        selected = selected[:-1]
    return start, end


def _has_strong_ending(segments: list[TranscriptSegment]) -> bool:
    if not segments:
        return False
    tail = " ".join(item.text.strip() for item in segments[-2:]).strip()
    return _has_payoff_marker(tail) or _has_terminal_punctuation(tail)


def _has_terminal_punctuation(text: str) -> bool:
    return text.strip().endswith((".", "!", "?", "…"))


def _has_payoff_marker(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "всё это время",
        "значит",
        "тогда",
        "оказывается",
        "правда",
        "секрет",
        "письмо",
        "деньги",
        "жив",
        "умер",
        "люблю",
        "ненавижу",
    ]
    return any(marker in lowered for marker in markers)


def _is_weak_opening(text: str) -> bool:
    lowered = text.strip().lower().strip(" ,.!?…")
    prefixes = ("ну", "ладно", "так", "слушай", "в общем", "короче", "погоди", "подожди")
    short_words = len(lowered.split()) <= 4
    return short_words and lowered.startswith(prefixes)


def _is_recap_or_credits(text: str) -> bool:
    lowered = text.lower()
    markers = ("ранее в сериале", "в предыдущих сериях", "продолжение следует", "в ролях", "режиссёр", "режиссер")
    return any(marker in lowered for marker in markers)


def dedupe_candidates(candidates: list[CandidatePayload], overlap_threshold: float = 0.65) -> list[CandidatePayload]:
    selected: list[CandidatePayload] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if all(_temporal_overlap(candidate, kept) < overlap_threshold for kept in selected):
            selected.append(candidate)
    return sorted(selected, key=lambda item: item.start_time)


def transcript_text(segments: list[TranscriptSegment]) -> str:
    return "\n".join(f"[{s.start_time:.1f}-{s.end_time:.1f}] {s.text}" for s in segments)


def _snap_to_scene_edges(start: float, end: float, scenes: list[Scene]) -> tuple[float, float]:
    for scene in scenes:
        if abs(scene.start_time - start) <= 1.0:
            start = scene.start_time
        if abs(scene.end_time - end) <= 1.0:
            end = scene.end_time
    return start, end


def _temporal_overlap(left: CandidatePayload, right: CandidatePayload) -> float:
    overlap = max(0.0, min(left.end_time, right.end_time) - max(left.start_time, right.start_time))
    shortest = min(left.end_time - left.start_time, right.end_time - right.start_time)
    if shortest <= 0:
        return 0.0
    return overlap / shortest
