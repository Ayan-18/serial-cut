from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.analysis.llm import LlamaCppHttpAnalyzer
from app.analysis.quality import calibrate_candidate
from app.analysis.schemas import CandidatePayload, CandidateScores, parse_candidate_json
from app.analysis.validation import adjust_candidate_boundaries, dedupe_candidates
from app.application.importer import import_season
from app.application.stage3 import run_stage3_candidate_analysis
from app.infrastructure.config import Settings
from app.models.entities import ClipCandidate, Episode, EpisodeOutline, Scene, TranscriptSegment, WordTimestamp


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


def test_content_style_classifies_and_feeds_the_clip_prompt(monkeypatch):
    calls: list[str] = []

    class Response:
        def __init__(self, body: dict) -> None:
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self._body, ensure_ascii=False)}}]}

    def fake_post(url, json, timeout):
        prompt = json["messages"][-1]["content"]
        calls.append(prompt)
        if "жанр этого видео" in prompt:
            return Response({"kind": "матч", "clip_focus": "жёлтые карточки и реакции игроков"})
        return Response({"candidates": [_candidate(0, 40).model_dump()]})

    monkeypatch.setattr("app.analysis.llm.httpx.post", fake_post)
    LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B").candidates(
        "[0.0-40.0] Судья показал жёлтую карточку.",
        [Scene(episode_id=1, start_time=0, end_time=40)],
    )

    clip_prompt = next(p for p in calls if "Работай только с частью серии" in p)
    assert "Тип видео: матч" in clip_prompt
    assert "жёлтые карточки" in clip_prompt


def test_content_style_failure_is_silent(monkeypatch):
    def boom(url, json, timeout):
        raise RuntimeError("model down")

    monkeypatch.setattr("app.analysis.llm.httpx.post", boom)
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")
    assert analyzer._content_style("[0.0-5.0] Привет") == ""


def test_llama_cpp_analyzer_builds_outline_without_http():
    result = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B").outline(
        "[0.0-20.0] Начало.\n[20.1-40.0] Развязка."
    )

    assert result.time_ranges[0].start_time == 0
    assert result.time_ranges[0].end_time == 40
    assert result.main_events == ["Начало. Развязка."]


def test_llama_cpp_analyzer_reports_missing_local_server(monkeypatch):
    request = httpx.Request("POST", "http://127.0.0.1:8081/v1/chat/completions")

    def missing_server(*args, **kwargs):
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr("app.analysis.llm.httpx.post", missing_server)
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")

    with pytest.raises(RuntimeError, match="Локальная Qwen недоступна"):
        analyzer.candidates(
            "[0.0-40.0] Текст",
            [Scene(episode_id=1, start_time=0, end_time=40)],
        )


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


def test_adjust_boundaries_never_caps_in_the_middle_of_a_spoken_segment():
    candidate = _candidate(657.28, 717.39)
    segments = [
        TranscriptSegment(episode_id=1, start_time=653.89, end_time=657.63, text="Начало до кандидата"),
        TranscriptSegment(episode_id=1, start_time=714.31, end_time=715.63, text="Законченная реплика?"),
        TranscriptSegment(episode_id=1, start_time=715.89, end_time=717.39, text="Следующая реплика?"),
    ]

    adjusted = adjust_candidate_boundaries(
        candidate,
        [],
        [],
        min_seconds=35,
        max_seconds=59,
        segments=segments,
    )

    assert adjusted is not None
    assert adjusted.start_time == 657.63
    assert adjusted.end_time == 715.63
    assert adjusted.end_time - adjusted.start_time <= 59


def test_adjust_boundaries_can_pull_in_missing_setup_replica():
    candidate = _candidate(24.4, 57.5)
    segments = [
        TranscriptSegment(episode_id=1, start_time=19.0, end_time=23.1, text="Ты опять пришёл сюда?"),
        TranscriptSegment(episode_id=1, start_time=24.0, end_time=31.0, text="Я пришёл не просить прощения."),
        TranscriptSegment(episode_id=1, start_time=32.0, end_time=42.0, text="Тогда зачем ты здесь?"),
        TranscriptSegment(episode_id=1, start_time=43.0, end_time=58.0, text="Потому что контракт всё ещё у меня."),
    ]

    adjusted = adjust_candidate_boundaries(
        candidate,
        [],
        [],
        min_seconds=25,
        max_seconds=45,
        segments=segments,
    )

    assert adjusted is not None
    assert adjusted.start_time == 19.0
    assert adjusted.end_time == 58.0


def test_quality_flags_a_boundary_inside_a_replica():
    candidate = _candidate(657.63, 716.28)
    segments = [
        TranscriptSegment(episode_id=1, start_time=657.63, end_time=715.63, text="Завершённая часть."),
        TranscriptSegment(episode_id=1, start_time=715.89, end_time=717.39, text="Обрезанная реплика?"),
    ]

    calibrated = calibrate_candidate(candidate, segments, [], [])

    assert "Конец попадает в середину реплики" in calibrated.possible_problems


def test_quality_penalizes_weak_standalone_moment():
    candidate = _candidate(70, 95, 72).model_copy(
        update={
            "title": "Мы пришли",
            "description": "Короткий проход без самостоятельной драматургии.",
            "standalone_reason": "Контекст слабый.",
        }
    )
    segments = [
        TranscriptSegment(episode_id=1, start_time=70, end_time=75, text="Ну, мы пришли."),
        TranscriptSegment(episode_id=1, start_time=76, end_time=80, text="Да."),
        TranscriptSegment(episode_id=1, start_time=81, end_time=85, text="Пошли."),
    ]

    calibrated = calibrate_candidate(candidate, segments, [], [])

    assert calibrated.score < candidate.score
    assert "Слабая концовка для короткого ролика" in calibrated.possible_problems


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


def test_stage3_replaces_candidates_that_have_edits_and_exports(session, tmp_path):
    from app.models.entities import CandidateEditSnapshot, Export

    season = tmp_path / "Сезон"
    season.mkdir()
    (season / "episode.mkv").write_bytes(b"video")
    episode_id = import_season(session, season).episode_ids[0]
    segment = TranscriptSegment(episode_id=episode_id, start_time=0, end_time=39, text="Сцена.")
    session.add_all([segment, Scene(episode_id=episode_id, start_time=0, end_time=40)])
    session.flush()

    settings = Settings(asr_adapter="stub", llm_adapter="stub")
    run_stage3_candidate_analysis(session, episode_id, settings)
    session.commit()
    candidate = session.scalar(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
    assert candidate is not None
    # The user edited and rendered this candidate: a snapshot + an export now
    # point at it (both FK -> clip_candidates.id).
    session.add(CandidateEditSnapshot(candidate_id=candidate.id, edit_revision=1, kind="geometry", label="x", state_json={}))
    session.add(Export(candidate_id=candidate.id, output_path="out.mp4"))
    session.commit()

    # Re-running stage 3 must not trip the FK constraint on those rows.
    run_stage3_candidate_analysis(session, episode_id, settings)
    session.commit()

    assert session.scalar(select(CandidateEditSnapshot).where(CandidateEditSnapshot.candidate_id == candidate.id)) is None
    assert session.scalar(select(Export).where(Export.candidate_id == candidate.id)) is None
    assert session.scalar(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id)) is not None


def test_story_mode_uses_context_and_numbers_candidates(session, tmp_path):
    season_dir = tmp_path / "story-season"
    season_dir.mkdir()
    (season_dir / "episode.mkv").write_bytes(b"video")
    episode_id = import_season(session, season_dir).episode_ids[0]
    episode = session.get(Episode, episode_id)
    assert episode is not None
    episode.season.story_context = "Команда пытается сохранить клуб."
    episode.story_summary = "Герои находят финансирование."
    episode.required_events_json = ["Разговор о финансировании"]
    episode.candidate_mode = "story"
    segment = TranscriptSegment(episode_id=episode_id, start_time=0, end_time=40, text="Цельная сцена.")
    session.add_all([segment, Scene(episode_id=episode_id, start_time=0, end_time=40)])
    session.commit()

    result = run_stage3_candidate_analysis(session, episode_id, Settings(llm_adapter="stub"))

    candidate = session.scalar(select(ClipCandidate).where(ClipCandidate.episode_id == episode_id))
    outline = session.scalar(select(EpisodeOutline).where(EpisodeOutline.episode_id == episode_id))
    assert result.candidates == 1
    assert candidate is not None and candidate.story_order == 1 and candidate.story_role == "завязка"
    assert outline is not None and outline.summary_json["summary"] == "Герои находят финансирование."

