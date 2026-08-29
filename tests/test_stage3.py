from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.analysis.llm import LlamaCppHttpAnalyzer
from app.analysis.schemas import CandidatePayload, CandidateScores, EpisodeOutlinePayload, parse_candidate_json
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates
from app.application.importer import import_season
from app.application.stage3 import run_stage3_candidate_analysis
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, Scene, TranscriptSegment, WordTimestamp


def _candidate(start: float, end: float, score: int = 80) -> CandidatePayload:
    return CandidatePayload(
        start_time=start,
        end_time=end,
        title="Момент",
        description="Описание",
        moment_type="другое",
        score=score,
        scores=CandidateScores(
            hook=score,
            standalone_context=score,
            payoff=score,
            emotion=score,
            boundary_quality=score,
            visual_potential=score,
            audio_quality=score,
        ),
        standalone_reason="Понятен отдельно",
    )


def test_parse_candidate_json_rejects_invalid_response():
    with pytest.raises(ValueError, match="невалидный JSON"):
        parse_candidate_json("не json")


def test_parse_candidate_json_accepts_code_fenced_payload():
    parsed = parse_candidate_json(
        '```json\n{"candidates":[{"start_time":1,"end_time":40,"title":"A","description":"B",'
        '"moment_type":"другое","characters":[],"score":81,'
        '"scores":{"hook":80,"standalone_context":80,"payoff":80,"emotion":80,'
        '"boundary_quality":80,"visual_potential":80,"audio_quality":80},'
        '"standalone_reason":"ok","possible_problems":[]}]}\n```'
    )

    assert parsed.candidates[0].score == 81


def test_parse_candidate_json_removes_qwen_thinking_wrapper():
    parsed = parse_candidate_json(
        '<think>не показывать рассуждение</think>\n'
        '{"candidates":[{"start_time":1,"end_time":40,"title":"A","description":"B",'
        '"moment_type":"другое","characters":[],"score":81,'
        '"scores":{"hook":80,"standalone_context":80,"payoff":80,"emotion":80,'
        '"boundary_quality":80,"visual_potential":80,"audio_quality":80},'
        '"standalone_reason":"ok","possible_problems":[]}]}'
    )

    assert parsed.candidates[0].score == 81


def test_llama_cpp_analyzer_uses_local_chat_completions(monkeypatch):
    captured: dict = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            payload = {"candidates": [_candidate(0, 40).model_dump()]}
            return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    def fake_post(url, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("app.analysis.llm.httpx.post", fake_post)
    result = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B").candidates(
        "[0.0-40.0] Текст", [Scene(episode_id=1, start_time=0, end_time=40)]
    )

    assert result.candidates[0].score == 80
    assert captured["url"] == "http://127.0.0.1:8081/v1/chat/completions"
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["json"]["response_format"]["schema"]["title"] == "CandidateListPayload"


def test_llama_cpp_analyzer_builds_outline_without_http():
    result = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B").outline(
        "[0.0-20.0] Начало.\n[20.1-40.0] Развязка."
    )

    assert result.time_ranges[0].start_time == 0
    assert result.time_ranges[0].end_time == 40
    assert result.main_events == ["Начало. Развязка."]


def test_adjust_boundaries_uses_word_padding_and_scene_edges():
    candidate = _candidate(10.1, 44.8)
    words = [WordTimestamp(segment_id=1, start_time=10.3, end_time=11.0, word="Привет")]
    scenes = [Scene(episode_id=1, start_time=10.0, end_time=45.0)]

    adjusted = adjust_candidate_boundaries(candidate, words, scenes, min_seconds=25, max_seconds=59)

    assert adjusted is not None
    assert adjusted.start_time == 10.0
    assert adjusted.end_time == 45.0


def test_adjust_boundaries_expands_short_candidate_to_minimum():
    candidate = _candidate(10, 20)
    scenes = [Scene(episode_id=1, start_time=0, end_time=100)]

    adjusted = adjust_candidate_boundaries(candidate, [], scenes, min_seconds=35, max_seconds=59)

    assert adjusted is not None
    assert adjusted.start_time == 10
    assert adjusted.end_time == 45


def test_dedupe_candidates_keeps_highest_scored_overlap():
    selected = dedupe_candidates([_candidate(0, 40, 70), _candidate(5, 42, 95), _candidate(80, 120, 60)])

    assert [candidate.score for candidate in selected] == [95, 60]


def test_stage3_smoke_generates_outline_and_candidates(session, tmp_path):
    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    imported = import_season(session, season)
    episode_id = imported.episode_ids[0]
    segment = TranscriptSegment(episode_id=episode_id, start_time=0, end_time=39, text="Тестовая русская сцена.")
    session.add(segment)
    session.flush()
    session.add(WordTimestamp(segment_id=segment.id, start_time=1, end_time=2, word="Тестовая"))
    session.add(Scene(episode_id=episode_id, start_time=0, end_time=40))

    result = run_stage3_candidate_analysis(
        session,
        episode_id,
        Settings(asr_adapter="stub", llm_adapter="stub"),
    )
    session.commit()

    assert result.candidates == 1
    assert session.scalar(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id)) is not None

