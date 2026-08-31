from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.analysis.quality import calibrate_candidate
from app.analysis.schemas import CandidatePayload
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates
from app.models.entities import Scene, TranscriptSegment, WordTimestamp


class TimeRangeFixture(BaseModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    label: str = ""


class SegmentFixture(TimeRangeFixture):
    text: str = Field(min_length=1)
    speaker_label: str | None = None


class SceneFixture(TimeRangeFixture):
    confidence: float | None = None


class WordFixture(TimeRangeFixture):
    segment_index: int = Field(ge=0)
    word: str = Field(min_length=1)


class QualityCaseFixture(BaseModel):
    name: str = Field(min_length=1)
    min_clip_seconds: int = Field(default=35, ge=1)
    max_clip_seconds: int = Field(default=59, ge=1)
    transcript_segments: list[SegmentFixture]
    scenes: list[SceneFixture] = Field(default_factory=list)
    words: list[WordFixture] = Field(default_factory=list)
    candidates: list[CandidatePayload]
    expected_good_ranges: list[TimeRangeFixture]


@dataclass(frozen=True)
class CandidateQualityResult:
    title: str
    start_time: float
    end_time: float
    score: int
    best_expected_overlap: float
    boundary_score: int
    problems: list[str]


@dataclass(frozen=True)
class QualityCaseResult:
    name: str
    candidate_quality: int
    boundary_quality: int
    expected_coverage: int
    precision: int
    duplicate_rate: int
    invalid_clips: int
    original_candidates: int
    selected_candidates: int
    candidates: list[CandidateQualityResult]

    @property
    def overall(self) -> int:
        duplicate_penalty = min(20, self.duplicate_rate // 3)
        invalid_penalty = self.invalid_clips * 10
        return max(
            0,
            round(
                self.candidate_quality * 0.45
                + self.boundary_quality * 0.30
                + self.expected_coverage * 0.15
                + self.precision * 0.10
                - duplicate_penalty
                - invalid_penalty
            ),
        )


def load_quality_case(path: Path) -> QualityCaseFixture:
    with path.open("r", encoding="utf-8") as handle:
        return QualityCaseFixture.model_validate(json.load(handle))


def evaluate_quality_case(case: QualityCaseFixture) -> QualityCaseResult:
    segments = _segments(case.transcript_segments)
    scenes = _scenes(case.scenes)
    words = _words(case.words, case.transcript_segments)
    adjusted: list[CandidatePayload] = []
    invalid_clips = 0

    for candidate in case.candidates:
        normalized = adjust_candidate_boundaries(
            candidate,
            words,
            scenes,
            case.min_clip_seconds,
            case.max_clip_seconds,
            segments=segments,
        )
        if normalized is None:
            invalid_clips += 1
            continue
        adjusted.append(calibrate_candidate(normalized, segments, scenes, words))

    selected = dedupe_candidates(adjusted)
    duplicate_rate = round(100 * (len(adjusted) - len(selected)) / len(adjusted)) if adjusted else 0
    expected_ranges = case.expected_good_ranges
    candidate_results = [
        _candidate_result(candidate, expected_ranges, segments) for candidate in selected
    ]
    hits = [item for item in candidate_results if item.best_expected_overlap >= 0.55]
    covered_expected = sum(
        1 for expected in expected_ranges if _best_overlap_for_range(expected, selected) >= 0.55
    )
    expected_coverage = round(100 * covered_expected / len(expected_ranges)) if expected_ranges else 100
    precision = round(100 * len(hits) / len(selected)) if selected else 0
    average_score = (
        round(sum(item.score for item in candidate_results) / len(candidate_results))
        if candidate_results
        else 0
    )
    candidate_quality = round(average_score * 0.45 + expected_coverage * 0.35 + precision * 0.20)
    boundary_quality = (
        round(sum(item.boundary_score for item in candidate_results) / len(candidate_results))
        if candidate_results
        else 0
    )

    return QualityCaseResult(
        name=case.name,
        candidate_quality=candidate_quality,
        boundary_quality=boundary_quality,
        expected_coverage=expected_coverage,
        precision=precision,
        duplicate_rate=duplicate_rate,
        invalid_clips=invalid_clips,
        original_candidates=len(case.candidates),
        selected_candidates=len(selected),
        candidates=candidate_results,
    )


def discover_quality_cases(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*.json") if item.is_file())


def format_quality_report(results: list[QualityCaseResult]) -> str:
    lines: list[str] = ["SerialCuts quality benchmark", "============================", ""]
    for result in results:
        lines.extend(
            [
                f"Case: {result.name}",
                f"Overall: {result.overall}/100",
                f"Candidate quality: {result.candidate_quality}/100",
                f"Boundary quality: {result.boundary_quality}/100",
                f"Expected coverage: {result.expected_coverage}%",
                f"Precision: {result.precision}%",
                f"Duplicate rate: {result.duplicate_rate}%",
                f"Invalid clips: {result.invalid_clips}",
                f"Selected: {result.selected_candidates}/{result.original_candidates}",
            ]
        )
        for candidate in result.candidates:
            problems = "; ".join(candidate.problems) if candidate.problems else "ok"
            lines.append(
                f"  - {candidate.title}: {candidate.start_time:.1f}-{candidate.end_time:.1f}, "
                f"score={candidate.score}, expected_overlap={candidate.best_expected_overlap:.2f}, "
                f"boundary={candidate.boundary_score}, {problems}"
            )
        lines.append("")
    if results:
        average = round(sum(result.overall for result in results) / len(results))
        lines.append(f"Average overall: {average}/100")
    else:
        lines.append("No quality cases found.")
    return "\n".join(lines)


def run_quality_benchmark(path: Path) -> list[QualityCaseResult]:
    return [evaluate_quality_case(load_quality_case(item)) for item in discover_quality_cases(path)]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run lightweight SerialCuts quality benchmark cases.")
    parser.add_argument("path", nargs="?", default="tests/quality", help="JSON case file or directory")
    parser.add_argument("--min-overall", type=int, default=70, help="minimum acceptable average score")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    results = run_quality_benchmark(Path(args.path))
    if args.json:
        print(json.dumps([_result_to_dict(item) for item in results], ensure_ascii=False, indent=2))
    else:
        print(format_quality_report(results))
    if not results:
        return 1
    average = round(sum(result.overall for result in results) / len(results))
    return 0 if average >= args.min_overall else 1


def _segments(fixtures: list[SegmentFixture]) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=index + 1,
            episode_id=1,
            start_time=item.start_time,
            end_time=item.end_time,
            text=item.text,
            speaker_label=item.speaker_label,
        )
        for index, item in enumerate(fixtures)
    ]


def _scenes(fixtures: list[SceneFixture]) -> list[Scene]:
    return [
        Scene(
            episode_id=1,
            start_time=item.start_time,
            end_time=item.end_time,
            confidence=item.confidence,
        )
        for item in fixtures
    ]


def _words(words: list[WordFixture], segments: list[SegmentFixture]) -> list[WordTimestamp]:
    if words:
        return [
            WordTimestamp(
                segment_id=item.segment_index + 1,
                start_time=item.start_time,
                end_time=item.end_time,
                word=item.word,
            )
            for item in words
        ]
    generated: list[WordTimestamp] = []
    for index, segment in enumerate(segments):
        parts = [part.strip() for part in segment.text.split() if part.strip()]
        if not parts:
            continue
        duration = max(0.1, segment.end_time - segment.start_time)
        step = duration / len(parts)
        for word_index, word in enumerate(parts):
            start = segment.start_time + word_index * step
            generated.append(
                WordTimestamp(
                    segment_id=index + 1,
                    start_time=round(start, 3),
                    end_time=round(min(segment.end_time, start + step * 0.85), 3),
                    word=word,
                )
            )
    return generated


def _candidate_result(
    candidate: CandidatePayload,
    expected_ranges: list[TimeRangeFixture],
    segments: list[TranscriptSegment],
) -> CandidateQualityResult:
    problems = list(candidate.possible_problems)
    boundary_score = candidate.scores.boundary_quality
    if _cuts_segment(candidate.start_time, segments):
        boundary_score = min(boundary_score, 45)
        problems.append("Начало внутри реплики")
    if _cuts_segment(candidate.end_time, segments):
        boundary_score = min(boundary_score, 45)
        problems.append("Конец внутри реплики")
    text = " ".join(
        segment.text
        for segment in segments
        if segment.start_time >= candidate.start_time - 0.05
        and segment.end_time <= candidate.end_time + 0.05
    ).strip()
    if text and not text.endswith((".", "!", "?", "…")):
        boundary_score = min(boundary_score, 70)
        problems.append("Нет явного завершения реплики")
    return CandidateQualityResult(
        title=candidate.title,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        score=candidate.score,
        best_expected_overlap=max(
            (
                _temporal_overlap(
                    candidate.start_time,
                    candidate.end_time,
                    item.start_time,
                    item.end_time,
                )
                for item in expected_ranges
            ),
            default=0.0,
        ),
        boundary_score=boundary_score,
        problems=_unique(problems),
    )


def _best_overlap_for_range(expected: TimeRangeFixture, candidates: list[CandidatePayload]) -> float:
    return max(
        (
            _temporal_overlap(candidate.start_time, candidate.end_time, expected.start_time, expected.end_time)
            for candidate in candidates
        ),
        default=0.0,
    )


def _cuts_segment(time: float, segments: list[TranscriptSegment]) -> bool:
    return any(segment.start_time + 0.05 < time < segment.end_time - 0.05 for segment in segments)


def _temporal_overlap(left_start: float, left_end: float, right_start: float, right_end: float) -> float:
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    shortest = min(left_end - left_start, right_end - right_start)
    if shortest <= 0:
        return 0.0
    return overlap / shortest


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _result_to_dict(result: QualityCaseResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "overall": result.overall,
        "candidate_quality": result.candidate_quality,
        "boundary_quality": result.boundary_quality,
        "expected_coverage": result.expected_coverage,
        "precision": result.precision,
        "duplicate_rate": result.duplicate_rate,
        "invalid_clips": result.invalid_clips,
        "original_candidates": result.original_candidates,
        "selected_candidates": result.selected_candidates,
        "candidates": [candidate.__dict__ for candidate in result.candidates],
    }


if __name__ == "__main__":
    raise SystemExit(main())
