from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.analysis.llm import LlamaCppHttpAnalyzer
from app.analysis.schemas import CandidatePayload, CandidateScores
from app.bot.callbacks import handle_candidate_callback
from app.infrastructure.config import Settings
from app.media.character_recognition import LocalFaceRecognizer, recognize_speaker_clusters
from app.models.entities import AppSetting, ClipCandidate


def _valid_candidates_payload() -> str:
    candidate = CandidatePayload(
        start_time=0.0,
        end_time=40.0,
        title="Момент",
        description="Описание",
        moment_type="другое",
        score=80,
        scores=CandidateScores(
            hook=80,
            standalone_context=80,
            payoff=80,
            emotion=80,
            boundary_quality=80,
            visual_potential=80,
            audio_quality=80,
        ),
        standalone_reason="Понятен отдельно",
    )
    return json.dumps({"candidates": [candidate.model_dump()]}, ensure_ascii=False)


class _Response:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


# --- LLM adapter: invalid JSON with a stricter retry ------------------------------


def test_llm_retries_once_when_first_json_response_is_broken(monkeypatch):
    responses = ["не json, а болтовня модели", _valid_candidates_payload()]
    calls: list[str] = []

    def fake_post(url, json, timeout):
        calls.append(json["messages"][-1]["content"])
        return _Response(responses[len(calls) - 1])

    monkeypatch.setattr("app.analysis.llm.httpx.post", fake_post)
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")

    result = analyzer.candidates("[0.0-40.0] Реплика", [])

    assert len(calls) == 2
    assert "не был валидным JSON" in calls[1]
    assert result.candidates and result.candidates[0].score == 80


def test_llm_raises_validation_error_when_every_retry_is_broken(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.llm.httpx.post",
        lambda url, json, timeout: _Response("<think>всё ещё не json</think>"),
    )
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")

    with pytest.raises(ValueError):
        analyzer.candidates("[0.0-40.0] Реплика", [])


# --- Telegram callbacks: a failed action must not poison the idempotency cache ----


def test_failed_telegram_export_is_not_cached_and_can_be_retried(session, monkeypatch):
    candidate = ClipCandidate(
        episode_id=1,
        start_time=0,
        end_time=35,
        title="Тест",
        description="Описание",
        moment_type="другое",
        score=90,
        scores_json={},
        rationale="Понятен",
        problems_json=[],
    )
    session.add(candidate)
    session.flush()

    calls = {"n": 0}

    def flaky_render(_session, _candidate_id, _settings):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("FFmpeg недоступен")

        class _Result:
            output_path = "C:/out/clip.mp4"

        return _Result()

    monkeypatch.setattr("app.bot.callbacks.render_candidate", flaky_render)

    with pytest.raises(RuntimeError):
        handle_candidate_callback(session, Settings(), "evt-1", "export", candidate.id)
    assert session.get(AppSetting, "telegram_callback:evt-1") is None

    result = handle_candidate_callback(session, Settings(), "evt-1", "export", candidate.id)
    assert result.status == "rendered"
    assert session.get(AppSetting, "telegram_callback:evt-1") is not None


# --- Face recognizer: graceful fallback when YuNet/SFace weights are missing ------


_FALLBACK_MODEL_NAMES = {
    "Haar + DCT (резервный режим)",
    "Только голос (лица не распознаются без YuNet/SFace)",
}


def test_face_recognizer_falls_back_without_onnx_weights(tmp_path: Path):
    engine = LocalFaceRecognizer(tmp_path / "missing_yunet.onnx", tmp_path / "missing_sface.onnx")

    assert engine.neural is False
    assert engine.model_name in _FALLBACK_MODEL_NAMES
    # No crash regardless of whether this OpenCV build still ships CascadeClassifier.
    assert engine.detect(np.zeros((240, 320, 3), dtype=np.uint8)) == []


def test_face_recognizer_falls_back_when_weights_are_corrupt(tmp_path: Path):
    detector = tmp_path / "yunet.onnx"
    recognizer = tmp_path / "sface.onnx"
    detector.write_bytes(b"not a real onnx model")
    recognizer.write_bytes(b"not a real onnx model")

    engine = LocalFaceRecognizer(detector, recognizer)

    assert engine.neural is False


def test_recognize_speaker_clusters_returns_fallback_model_name_with_no_profiles(tmp_path: Path):
    suggestions, model_name = recognize_speaker_clusters(
        tmp_path / "episode.mp4",
        {},
        [],
        tmp_path / "missing_yunet.onnx",
        tmp_path / "missing_sface.onnx",
    )

    assert suggestions == []
    assert model_name in _FALLBACK_MODEL_NAMES
