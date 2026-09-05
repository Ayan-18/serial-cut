from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.analysis.llm import LlamaCppHttpAnalyzer
from app.analysis.schemas import CandidatePayload, CandidateScores
from app.media.character_recognition import LocalFaceRecognizer, recognize_speaker_clusters
from app.models.entities import ClipCandidate


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
    calls: list[str] = []

    def fake_post(url, json, timeout):
        prompt = json["messages"][-1]["content"]
        calls.append(prompt)
        if "жанр этого видео" in prompt:  # the content-style classification call
            return _Response('{"kind": "тест", "clip_focus": "тест"}')
        # first candidates attempt: broken; the stricter retry: valid
        candidate_attempts = [p for p in calls if "жанр этого видео" not in p]
        return _Response(
            "не json, а болтовня модели" if len(candidate_attempts) == 1 else _valid_candidates_payload()
        )

    monkeypatch.setattr("app.analysis.llm.httpx.post", fake_post)
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")

    result = analyzer.candidates("[0.0-40.0] Реплика", [])

    retry_prompt = [p for p in calls if "не был валидным JSON" in p]
    assert len(retry_prompt) == 1
    assert result.candidates and result.candidates[0].score == 80


def test_llm_raises_validation_error_when_every_retry_is_broken(monkeypatch):
    monkeypatch.setattr(
        "app.analysis.llm.httpx.post",
        lambda url, json, timeout: _Response("<think>всё ещё не json</think>"),
    )
    analyzer = LlamaCppHttpAnalyzer("http://127.0.0.1:8081", "Qwen3-4B")

    with pytest.raises(ValueError):
        analyzer.candidates("[0.0-40.0] Реплика", [])


# --- Face recognizer: graceful fallback when YuNet/SFace weights are missing ------


def test_face_recognizer_falls_back_without_onnx_weights(tmp_path: Path):
    engine = LocalFaceRecognizer(tmp_path / "missing_yunet.onnx", tmp_path / "missing_sface.onnx")

    assert engine.neural is False
    assert engine.can_detect is False
    assert engine.model_name == "Только голос (лица не распознаются без YuNet/SFace)"
    assert engine.detect(np.zeros((240, 320, 3), dtype=np.uint8)) == []


def test_face_recognizer_falls_back_when_weights_are_corrupt(tmp_path: Path):
    detector = tmp_path / "yunet.onnx"
    recognizer = tmp_path / "sface.onnx"
    detector.write_bytes(b"not a real onnx model")
    recognizer.write_bytes(b"not a real onnx model")

    engine = LocalFaceRecognizer(detector, recognizer)

    assert engine.neural is False


def test_face_tracking_reports_unavailable_without_a_detector(tmp_path: Path, monkeypatch):
    from app.media import face_tracking

    result = face_tracking.estimate_face_offset(
        tmp_path / "missing.mp4",
        0.0,
        10.0,
        detector_model=tmp_path / "no_yunet.onnx",
        recognizer_model=tmp_path / "no_sface.onnx",
    )

    assert result.face_detection_available is False
    assert result.offset_x == 0.0
    assert result.keyframes == []


def test_auto_crop_endpoint_returns_422_when_face_models_are_missing(api_client, monkeypatch):
    from app.media.face_tracking import FaceTrackingResult
    from app.models.entities import Episode, Season

    def no_detector(*args, **kwargs):
        return FaceTrackingResult(
            offset_x=0.0,
            faces_detected=0,
            frames_sampled=0,
            keyframes=[],
            active_speaker_frames=0,
            identified_speaker_frames=0,
            lip_motion_frames=0,
            face_model="Только голос (лица не распознаются без YuNet/SFace)",
            held_frames=0,
            largest_face_frames=0,
            average_confidence=0.0,
            face_detection_available=False,
        )

    monkeypatch.setattr("app.media.face_tracking.estimate_face_offset", no_detector)

    session = api_client.db
    season = Season(title="S", root_path="C:/face-demo")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id,
        file_path="C:/face-demo/e.mkv",
        file_name="e.mkv",
        fingerprint="fp-face-crop",
        size_bytes=1,
        modified_ns=1,
        proxy_path="C:/face-demo/proxy.mp4",
        duration_seconds=60.0,
    )
    session.add(episode)
    session.flush()
    candidate = ClipCandidate(
        episode_id=episode.id,
        start_time=1.0,
        end_time=20.0,
        title="M",
        description="d",
        moment_type="другое",
        score=80,
        scores_json={},
        rationale="r",
        problems_json=[],
    )
    session.add(candidate)
    session.commit()

    response = api_client.post(f"/api/candidates/{candidate.id}/auto-crop")

    assert response.status_code == 422
    assert "YuNet/SFace" in response.json()["detail"]
    # The candidate crop mode must be left untouched.
    assert session.get(ClipCandidate, candidate.id).crop_mode == "center-crop"


def test_recognize_speaker_clusters_returns_fallback_model_name_with_no_profiles(tmp_path: Path):
    suggestions, model_name = recognize_speaker_clusters(
        tmp_path / "episode.mp4",
        {},
        [],
        tmp_path / "missing_yunet.onnx",
        tmp_path / "missing_sface.onnx",
    )

    assert suggestions == []
    assert model_name == "Только голос (лица не распознаются без YuNet/SFace)"
