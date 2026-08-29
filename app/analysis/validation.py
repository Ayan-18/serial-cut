from __future__ import annotations

from app.analysis.schemas import CandidatePayload
from app.models.entities import Scene, TranscriptSegment, WordTimestamp


def adjust_candidate_boundaries(
    candidate: CandidatePayload,
    words: list[WordTimestamp],
    scenes: list[Scene],
    min_seconds: int,
    max_seconds: int,
) -> CandidatePayload | None:
    start = max(0.0, candidate.start_time)
    end = candidate.end_time
    nearby_words = [word for word in words if word.end_time >= start - 2 and word.start_time <= end + 2]
    spoken_words = [word for word in nearby_words if word.start_time >= start and word.end_time <= end]
    if spoken_words:
        start = max(0.0, min(start, spoken_words[0].start_time - 0.35))
        end = max(end, spoken_words[-1].end_time + 0.55)

    start, end = _snap_to_scene_edges(start, end, scenes)
    duration = end - start
    if duration < min_seconds:
        episode_end = max((scene.end_time for scene in scenes), default=start + min_seconds)
        end = min(start + min_seconds, episode_end)
        if end - start < min_seconds:
            start = max(0.0, end - min_seconds)
        start, end = _snap_to_scene_edges(start, end, scenes)
    if end - start > max_seconds:
        end = start + max_seconds
    if end <= start or end - start < min_seconds:
        return None
    return candidate.model_copy(update={"start_time": round(start, 3), "end_time": round(end, 3)})


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
