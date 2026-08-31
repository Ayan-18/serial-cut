from __future__ import annotations

import json
from pathlib import Path

from app.analysis.benchmark import (
    evaluate_quality_case,
    format_quality_report,
    load_quality_case,
    run_quality_benchmark,
)


def test_quality_fixture_scores_above_gate():
    result = evaluate_quality_case(load_quality_case(Path("tests/quality/story_dialogue.json")))

    assert result.overall >= 70
    assert result.expected_coverage == 100
    assert result.duplicate_rate > 0
    assert result.invalid_clips == 0
    assert result.selected_candidates < result.original_candidates


def test_quality_report_contains_human_readable_metrics():
    results = run_quality_benchmark(Path("tests/quality"))
    report = format_quality_report(results)

    assert "SerialCuts quality benchmark" in report
    assert "Candidate quality:" in report
    assert "Boundary quality:" in report
    assert "Average overall:" in report


def test_quality_benchmark_json_mode_is_serializable():
    result = evaluate_quality_case(load_quality_case(Path("tests/quality/story_dialogue.json")))
    payload = {
        "name": result.name,
        "overall": result.overall,
        "candidates": [candidate.__dict__ for candidate in result.candidates],
    }

    encoded = json.dumps(payload, ensure_ascii=False)
    assert "story_dialogue" in encoded

