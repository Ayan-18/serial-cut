from __future__ import annotations

import numpy as np

from app.media import face_tracking
from app.media.character_recognition import FaceObservation
from app.media.face_tracking import (
    SpeechRange,
    _active_speech,
    _aggregate_label_positions,
    _build_trajectory,
    _CentroidTracker,
    _prefetch_frames,
    _Sample,
    estimate_face_offset,
)


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


def test_centroid_tracker_keeps_one_id_for_a_moving_face_and_forks_on_a_new_one():
    tracker = _CentroidTracker()

    assert tracker.assign([0.2]) == [0]
    assert tracker.assign([0.28]) == [0]  # same person drifted a little
    assert tracker.assign([0.34]) == [0]
    # A second face appears far away -> a new id, the first keeps its id.
    assert tracker.assign([0.4, 0.85]) == [0, 1]
    assert tracker.assign([0.85]) == [1]  # only the second remains


class _FakeCapture:
    """Minimal cv2.VideoCapture: 25 fps, frames numbered by their index."""

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


def test_prefetch_frames_reads_each_wanted_timestamp_once():
    import cv2

    capture = _FakeCapture()

    frames = _prefetch_frames(capture, [1.0, 1.5, 2.0], cv2)

    assert sorted(frames) == [1.0, 1.5, 2.0]
    assert frames[1.0].max() == min(255, round(1.0 * 25))
    assert frames[2.0].max() == min(255, round(2.0 * 25))


class _OpenCapture(_FakeCapture):
    def isOpened(self) -> bool:  # noqa: N802 - cv2 API name
        return True

    def release(self) -> None:
        return None


class _SlidingFace:
    """One face that slides slowly left→right across a 100 px frame."""

    model_name = "YuNet + SFace (fake)"
    can_detect = True
    neural = True

    def __init__(self, *args, **kwargs) -> None:
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        cx = 10 + min(80, self.calls * 2)
        return [FaceObservation(x=int(cx), y=40, width=20, height=20, score=0.9,
                                embedding=np.ones(3, dtype=np.float32))]


def test_estimate_face_offset_centres_when_nobody_is_talking(monkeypatch):
    monkeypatch.setattr(face_tracking, "LocalFaceRecognizer", _SlidingFace)
    monkeypatch.setattr(face_tracking, "build_reference_vectors", lambda engine, profiles: [])
    monkeypatch.setattr("cv2.VideoCapture", lambda path: _OpenCapture())
    monkeypatch.setattr(_OpenCapture, "retrieve",
                        lambda self: (True, np.full((100, 100, 3), min(255, self._grabbed), np.uint8)))

    # No speech ranges -> no confident talking subject -> the shot is just centred
    # and dead still, not a pan chasing the moving face.
    result = estimate_face_offset("clip.mp4", 0.0, 6.0, samples=18)

    assert result.face_detection_available is True
    offsets = [k["offset"] for k in result.keyframes]
    assert all(abs(o) < 0.05 for o in offsets)  # centred
    assert max(offsets) - min(offsets) < 0.02  # no jitter


def _talk_sample(rel_time: float, label: str, talker_left: bool) -> _Sample:
    """Two faces at 0.3 and 0.7; the left or right one moves its mouth."""
    lip = {0: 0.35, 1: 0.02} if talker_left else {0: 0.02, 1: 0.35}
    return _Sample(
        rel_time=rel_time,
        centers=[0.3, 0.7],
        areas=[400.0, 400.0],
        track_ids=[0, 1],
        lip_scores=lip,
        active=SpeechRange(rel_time - 0.1, rel_time + 0.1, source_label=label),
        audio_energy=1.0,
        identified_center=None,
    )


def _offset_at(keyframes, t: float) -> float:
    prev = keyframes[0]
    for kf in keyframes:
        if kf["time"] >= t:
            if kf["time"] == prev["time"]:
                return kf["offset"]
            r = (t - prev["time"]) / (kf["time"] - prev["time"])
            return prev["offset"] + (kf["offset"] - prev["offset"]) * r
        prev = kf
    return keyframes[-1]["offset"]


def test_trajectory_glides_smoothly_between_speakers():
    # Speaker A (left) talks for 3 s at 0.2 s cadence, then speaker B (right).
    samples = [_talk_sample(i * 0.2, "A", talker_left=True) for i in range(15)]
    samples += [_talk_sample(3.0 + i * 0.2, "B", talker_left=False) for i in range(20)]

    positions = _aggregate_label_positions(samples)
    assert positions["A"] < 0.4 < positions["B"]

    keyframes, _ = _build_trajectory(samples, positions)

    # No teleport in a single step.
    assert all(abs(b["offset"] - a["offset"]) < 0.7 for a, b in zip(keyframes, keyframes[1:]))
    before = _offset_at(keyframes, 2.8)
    after = _offset_at(keyframes, 4.5)
    assert before < -0.3 and after > 0.3  # framed A, then B

    # The swing is a glide: monotone (no overshoot), and it is neither an instant
    # cut nor a multi-second drift.
    swing = [_offset_at(keyframes, 3.0 + i * 0.1) for i in range(13)]
    assert all(b >= a - 1e-6 for a, b in zip(swing, swing[1:]))  # monotone, no oscillation
    assert swing[1] - swing[0] < 0.45  # not a cut in the first 0.1 s
    assert swing[8] > 0.3  # but well across within ~0.8 s


def test_trajectory_holds_still_while_one_speaker_talks():
    samples = [_talk_sample(i * 0.25, "A", talker_left=True) for i in range(16)]
    keyframes, _ = _build_trajectory(samples, _aggregate_label_positions(samples))
    tail = [k["offset"] for k in keyframes if k["time"] > 1.0]  # after it settles
    assert max(tail) - min(tail) < 0.02  # dead still
