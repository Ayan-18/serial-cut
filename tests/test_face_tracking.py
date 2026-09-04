from __future__ import annotations

import numpy as np

from app.media import face_tracking
from app.media.character_recognition import FaceObservation
from app.media.face_tracking import (
    SpeechRange,
    _active_speech,
    _prefetch_frames,
    _smooth_keyframes,
    estimate_face_offset,
)


def test_smooth_keyframes_clamps_step_and_eases_toward_target():
    # A hard jump toward 1.0 must ramp, never teleport between frames.
    detections = [(t / 2, 0.0 if t == 0 else 1.0, 0.0, -1.0) for t in range(6)]

    frames = _smooth_keyframes(detections)

    offsets = [f["offset"] for f in frames]
    assert [f["time"] for f in frames] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert offsets == sorted(offsets)  # monotonic toward the target
    assert all(abs(b - a) <= 0.25 for a, b in zip(offsets, offsets[1:]))  # step-limited
    assert offsets[-1] < 1.0  # easing never fully arrives inside the window


def test_active_speech_prefers_the_shortest_identified_range():
    ranges = [
        SpeechRange(0.0, 10.0, character_id=None),
        SpeechRange(1.0, 3.0, character_id=7),
        SpeechRange(0.5, 9.0, character_id=9),
    ]

    picked = _active_speech(2.0, ranges)

    assert picked is not None and picked.character_id == 7


def test_active_speech_returns_none_outside_every_range():
    assert _active_speech(50.0, [SpeechRange(0.0, 1.0)]) is None


class _FakeCapture:
    """Minimal cv2.VideoCapture: 25 fps, frames numbered by their index.

    Mirrors cv2 semantics: ``grab()`` latches the current frame and advances,
    ``retrieve()`` decodes the latched frame.
    """

    def __init__(self, fps: float = 25.0) -> None:
        self.fps = fps
        self._pos = 0
        self._grabbed = 0

    def get(self, prop: int) -> float:
        if prop == 5:  # CAP_PROP_FPS
            return self.fps
        if prop == 1:  # CAP_PROP_POS_FRAMES
            return float(self._pos)
        return 0.0

    def set(self, prop: int, value: float) -> bool:
        if prop == 1:
            self._pos = int(value)
        return True

    def grab(self) -> bool:
        self._grabbed = self._pos
        self._pos += 1
        return self._grabbed < 10_000

    def retrieve(self):
        frame = np.full((4, 4, 3), min(255, self._grabbed), dtype=np.uint8)
        return True, frame


def test_prefetch_frames_reads_each_wanted_timestamp_once(monkeypatch):
    import cv2

    capture = _FakeCapture()
    wanted = [1.0, 1.5, 2.0]

    frames = _prefetch_frames(capture, wanted, cv2)

    assert sorted(frames) == [1.0, 1.5, 2.0]
    # frame value tracks the decoded frame index (~ts * fps), proving a forward scan
    assert frames[1.0].max() == min(255, round(1.0 * 25))
    assert frames[2.0].max() == min(255, round(2.0 * 25))


class _FakeEngine:
    """Face detector stub: one face that slides left→right across the window."""

    model_name = "YuNet + SFace (fake)"
    can_detect = True
    neural = True

    def __init__(self, *args, **kwargs) -> None:
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        # frame width is 4 in the fake; move the face center from x≈0 to x≈4
        progress = min(1.0, self.calls / 12)
        cx = progress * 4
        return [
            FaceObservation(
                x=int(cx), y=1, width=1, height=1, score=0.9, embedding=np.ones(3, dtype=np.float32)
            )
        ]


def test_estimate_face_offset_tracks_a_face_moving_left_to_right(monkeypatch):
    monkeypatch.setattr(face_tracking, "LocalFaceRecognizer", _FakeEngine)
    monkeypatch.setattr(face_tracking, "build_reference_vectors", lambda engine, profiles: [])

    class _OpenCapture(_FakeCapture):
        def isOpened(self) -> bool:  # noqa: N802 - cv2 API name
            return True

        def release(self) -> None:
            return None

    monkeypatch.setattr("cv2.VideoCapture", lambda path: _OpenCapture())

    result = estimate_face_offset("clip.mp4", 0.0, 4.0, samples=12)

    assert result.face_detection_available is True
    assert result.face_model == "YuNet + SFace (fake)"
    assert result.frames_sampled > 0
    assert result.keyframes[0]["offset"] < result.keyframes[-1]["offset"]  # follows the face right
