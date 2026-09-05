from __future__ import annotations

import numpy as np

from app.media import face_tracking
from app.media.character_recognition import FaceObservation
from app.media.face_tracking import (
    CUT_GAP_SECONDS,
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


def test_estimate_face_offset_follows_a_slowly_moving_face_without_cutting(monkeypatch):
    monkeypatch.setattr(face_tracking, "LocalFaceRecognizer", _SlidingFace)
    monkeypatch.setattr(face_tracking, "build_reference_vectors", lambda engine, profiles: [])
    monkeypatch.setattr("cv2.VideoCapture", lambda path: _OpenCapture())
    monkeypatch.setattr(_OpenCapture, "retrieve",
                        lambda self: (True, np.full((100, 100, 3), min(255, self._grabbed), np.uint8)))

    result = estimate_face_offset("clip.mp4", 0.0, 6.0, samples=18)

    assert result.face_detection_available is True
    assert result.keyframes[0]["offset"] < result.keyframes[-1]["offset"]  # tracks rightward
    # A single moving face must not trigger hard cuts: successive keyframes stay
    # spaced out in time.
    times = [k["time"] for k in result.keyframes]
    assert all(b - a >= CUT_GAP_SECONDS - 1e-9 for a, b in zip(times, times[1:]))


def _talk_sample(rel_time: float, label: str, talker_left: bool) -> _Sample:
    """Two faces at 0.15 and 0.85; the left or right one moves its mouth."""
    lip = {0: 0.35, 1: 0.02} if talker_left else {0: 0.02, 1: 0.35}
    return _Sample(
        rel_time=rel_time,
        centers=[0.15, 0.85],
        areas=[400.0, 400.0],
        track_ids=[0, 1],
        lip_scores=lip,
        active=SpeechRange(rel_time - 0.1, rel_time + 0.1, source_label=label),
        audio_energy=1.0,
        identified_center=None,
    )


def test_trajectory_cuts_hard_between_two_speakers():
    # Speaker A (left) talks for 3 s, then speaker B (right) takes over.
    samples = [_talk_sample(t / 2, "A", talker_left=True) for t in range(6)]
    samples += [_talk_sample(3.0 + t / 2, "B", talker_left=False) for t in range(6)]

    positions = _aggregate_label_positions(samples)
    assert positions["A"] < 0.4 < positions["B"]

    keyframes, _ = _build_trajectory(samples, positions)
    cut_pairs = [
        (a, b)
        for a, b in zip(keyframes, keyframes[1:])
        if b["time"] - a["time"] <= CUT_GAP_SECONDS + 1e-6 and abs(b["offset"] - a["offset"]) > 0.5
    ]
    assert cut_pairs, "a speaker change must produce one hard cut, not a slow pan"
    # ...and only around the 3 s boundary, not on every frame.
    assert len(cut_pairs) == 1
    assert 2.5 < cut_pairs[0][1]["time"] < 3.2


def test_trajectory_holds_steady_while_one_speaker_talks():
    samples = [_talk_sample(t / 3, "A", talker_left=True) for t in range(12)]
    keyframes, _ = _build_trajectory(samples, _aggregate_label_positions(samples))
    offsets = [k["offset"] for k in keyframes]
    assert max(offsets) - min(offsets) < 0.15  # basically still
