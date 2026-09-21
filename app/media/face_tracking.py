from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np

from app.media.character_recognition import (
    CharacterProfile,
    LocalFaceRecognizer,
    build_reference_vectors,
    mouth_motion_score,
)
from app.media.face_tracking_trajectory import (
    CUT_GAP_SECONDS,
    _Sample,
    _active_speech,
    _aggregate_label_positions,
    _audio_activity,
    _build_trajectory,
    _CentroidTracker,
    _face_for_character,
    _load_audio,
    _motion_center,
    _prefetch_frames,
    _sample_times,
    _scene_cut_times,
)

# Re-exported for backwards compatibility — the trajectory-building engine
# (everything past "detect faces in the sampled frames") moved to
# face_tracking_trajectory.py. `LocalFaceRecognizer` and `build_reference_vectors`
# stayed imported here because `estimate_face_offset` is what tests monkeypatch
# them on (`app.media.face_tracking.LocalFaceRecognizer`), so it had to keep
# calling them as bare names in this module's namespace.
__all__ = [
    "SpeechRange",
    "FaceTrackingResult",
    "CUT_GAP_SECONDS",
    "estimate_face_offset",
]


@dataclass(frozen=True)
class SpeechRange:
    start_time: float
    end_time: float
    source_label: str | None = None
    character_id: int | None = None


@dataclass(frozen=True)
class FaceTrackingResult:
    offset_x: float
    faces_detected: int
    frames_sampled: int
    keyframes: list[dict[str, float]]
    active_speaker_frames: int
    identified_speaker_frames: int
    lip_motion_frames: int
    face_model: str
    held_frames: int
    largest_face_frames: int
    average_confidence: float
    face_detection_available: bool = True


def estimate_face_offset(
    video_path: Path,
    start_time: float,
    end_time: float,
    samples: int | None = None,
    speech_ranges: list[SpeechRange] | None = None,
    character_profiles: list[CharacterProfile] | None = None,
    detector_model: Path | None = None,
    recognizer_model: Path | None = None,
    audio_path: Path | None = None,
    scene_boundaries: list[float] | None = None,
) -> FaceTrackingResult:
    import cv2

    engine = LocalFaceRecognizer(detector_model, recognizer_model)
    if not engine.can_detect:
        # No YuNet/SFace weights and this OpenCV build has no Haar fallback:
        # there is nothing to track, so say so instead of silently centering.
        return FaceTrackingResult(
            offset_x=0.0,
            faces_detected=0,
            frames_sampled=0,
            keyframes=[],
            active_speaker_frames=0,
            identified_speaker_frames=0,
            lip_motion_frames=0,
            face_model=engine.model_name,
            held_frames=0,
            largest_face_frames=0,
            average_confidence=0.0,
            face_detection_available=False,
        )
    ranges = list(speech_ranges or [])
    references = build_reference_vectors(engine, character_profiles or [])
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для анализа лиц")

    sample_times = _sample_times(start_time, end_time, ranges, samples)
    audio = _load_audio(audio_path)
    wanted = sample_times + [max(start_time, t - 0.1) for t in sample_times]
    frames = _prefetch_frames(capture, wanted, cv2)
    _seed = next(iter(frames.values()), None)
    source_aspect = (_seed.shape[1] / _seed.shape[0]) if _seed is not None else 16 / 9

    samples_data: list[_Sample] = []
    faces_detected = 0
    tracker = _CentroidTracker()
    try:
        for timestamp in sample_times:
            current = frames.get(round(timestamp, 2))
            previous = frames.get(round(max(start_time, timestamp - 0.1), 2))
            if current is None:
                continue
            width = current.shape[1]
            current_faces = engine.detect(current)
            faces_detected += len(current_faces)
            rel_time = round(timestamp - start_time, 3)
            active = _active_speech(timestamp, ranges)
            audio_energy = _audio_activity(audio, timestamp)
            motion_center = _motion_center(current, previous)
            if not current_faces:
                samples_data.append(
                    _Sample(rel_time, [], [], [], {}, active, audio_energy, None, motion_center)
                )
                continue

            centers = [face.center_x / max(1, width) for face in current_faces]
            areas = [float(face.width * face.height) for face in current_faces]
            track_ids = tracker.assign(centers)
            lip_scores: dict[int, float] = {}
            if previous is not None:
                previous_faces = engine.detect(previous)
                if previous_faces:
                    for index, face in enumerate(current_faces):
                        near = min(
                            previous_faces,
                            key=lambda p: np.hypot(face.center_x - p.center_x, face.center_y - p.center_y),
                        )
                        diag = float(np.hypot(current.shape[1], current.shape[0]))
                        if float(np.hypot(face.center_x - near.center_x, face.center_y - near.center_y)) / diag <= 0.2:
                            lip_scores[index] = mouth_motion_score(current, face, previous, near, cv2)

            identified_center: float | None = None
            if active is not None and active.character_id is not None and references:
                selected, _ = _face_for_character(current_faces, references, active.character_id)
                if selected is not None:
                    identified_center = selected.center_x / max(1, width)

            samples_data.append(
                _Sample(
                    rel_time=rel_time,
                    centers=centers,
                    areas=areas,
                    track_ids=track_ids,
                    lip_scores=lip_scores,
                    active=active,
                    audio_energy=audio_energy,
                    identified_center=identified_center,
                    motion_center=motion_center,
                )
            )
    finally:
        capture.release()

    cut_times = _scene_cut_times(scene_boundaries, start_time, end_time)
    label_positions = _aggregate_label_positions(samples_data)
    keyframes, stats = _build_trajectory(samples_data, label_positions, source_aspect, cut_times)

    return FaceTrackingResult(
        offset_x=round(float(median(k["offset"] for k in keyframes)) if keyframes else 0.0, 3),
        faces_detected=faces_detected,
        frames_sampled=sum(1 for s in samples_data if s.centers),
        keyframes=keyframes,
        active_speaker_frames=stats["active_speaker"],
        identified_speaker_frames=stats["identified"],
        lip_motion_frames=stats["lip"],
        face_model=engine.model_name,
        held_frames=stats["held"],
        largest_face_frames=stats["largest"],
        average_confidence=round(stats["avg_lip"], 3),
    )
