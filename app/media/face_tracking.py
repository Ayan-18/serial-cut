from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np

from app.media.character_recognition import (
    CharacterProfile,
    FaceObservation,
    LocalFaceRecognizer,
    best_character_match,
    build_reference_vectors,
    select_lip_active_face,
)


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
    references = build_reference_vectors(engine, character_profiles or [])
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для анализа лиц")
    detections: list[tuple[float, float, float, float]] = []
    frames_sampled = 0
    faces_detected = 0
    active_speaker_frames = 0
    identified_speaker_frames = 0
    lip_motion_frames = 0
    duration = max(0.1, end_time - start_time)
    samples = samples or min(96, max(24, round(duration * 0.9)))
    audio = _load_audio(audio_path)
    held_frames = 0
    largest_face_frames = 0
    last_center: float | None = None
    last_offset: float | None = None
    sample_times = [start_time + duration * (index + 0.5) / samples for index in range(samples)]
    wanted = sample_times + [max(start_time, t - 0.12) for t in sample_times]
    frames = _prefetch_frames(capture, wanted, cv2)
    try:
        for timestamp in sample_times:
            current = frames.get(round(timestamp, 2))
            previous = frames.get(round(max(start_time, timestamp - 0.12), 2))
            if current is None:
                continue
            frames_sampled += 1
            current_faces = engine.detect(current)
            faces_detected += len(current_faces)
            if not current_faces:
                if last_offset is not None:
                    detections.append((timestamp - start_time, last_offset, 0.0, -1.0))
                    held_frames += 1
                continue
            active = _active_speech(timestamp, speech_ranges or [])
            selected: FaceObservation | None = None
            lip_score = 0.0
            selected_character_id = -1
            if active is not None and active.character_id is not None and references:
                selected, identity_score = _face_for_character(
                    current_faces, references, active.character_id
                )
                if selected is not None:
                    selected_character_id = active.character_id
                    identified_speaker_frames += 1
                    lip_score = identity_score
            if selected is None and active is not None and previous is not None:
                previous_faces = engine.detect(previous)
                selected, lip_score = select_lip_active_face(
                    current, current_faces, previous, previous_faces, cv2
                )
                lip_score *= _audio_activity(audio, timestamp)
                if selected is not None and lip_score >= 0.012:
                    lip_motion_frames += 1
                else:
                    selected = None
            if selected is None:
                nearby = (
                    min(current_faces, key=lambda face: abs(face.center_x / current.shape[1] - last_center))
                    if last_center is not None
                    else None
                )
                if nearby is not None and abs(nearby.center_x / current.shape[1] - last_center) <= 0.22:
                    selected = nearby
                    held_frames += 1
                else:
                    selected = max(current_faces, key=lambda face: face.width * face.height)
                    largest_face_frames += 1
            elif active is not None:
                active_speaker_frames += 1
            width = current.shape[1]
            center = selected.center_x / max(1, width)
            last_center = center
            last_offset = max(-1.0, min(1.0, (center - 0.5) * 2))
            detections.append(
                (
                    timestamp - start_time,
                    last_offset,
                    max(0.0, min(2.0, lip_score)),
                    float(selected_character_id),
                )
            )
    finally:
        capture.release()
    keyframes = _smooth_keyframes(detections)
    return FaceTrackingResult(
        offset_x=round(float(median(item["offset"] for item in keyframes)) if keyframes else 0.0, 3),
        faces_detected=faces_detected,
        frames_sampled=frames_sampled,
        keyframes=keyframes,
        active_speaker_frames=active_speaker_frames,
        identified_speaker_frames=identified_speaker_frames,
        lip_motion_frames=lip_motion_frames,
        face_model=engine.model_name,
        held_frames=held_frames,
        largest_face_frames=largest_face_frames,
        average_confidence=round(
            sum(item[2] for item in detections) / len(detections) if detections else 0.0,
            3,
        ),
    )


def _load_audio(audio_path: Path | None):
    if audio_path is None or not audio_path.exists():
        return None
    try:
        from app.media.speakers import _read_mono_pcm

        return _read_mono_pcm(audio_path)
    except Exception:
        return None


def _audio_activity(audio, timestamp: float) -> float:
    if audio is None:
        return 1.0
    sample_rate, samples = audio
    left = max(0, round((timestamp - 0.12) * sample_rate))
    right = min(len(samples), round((timestamp + 0.12) * sample_rate))
    if right <= left:
        return 0.0
    energy = float(np.sqrt(np.mean(samples[left:right] ** 2)))
    return max(0.0, min(1.0, energy / 0.025))


def _active_speech(timestamp: float, ranges: list[SpeechRange]) -> SpeechRange | None:
    active = [item for item in ranges if item.start_time - 0.08 <= timestamp <= item.end_time + 0.08]
    if not active:
        return None
    identified = [item for item in active if item.character_id is not None]
    candidates = identified or active
    return min(candidates, key=lambda item: item.end_time - item.start_time)


def _face_for_character(
    faces: list[FaceObservation],
    references: list[tuple[int, str, np.ndarray]],
    character_id: int,
) -> tuple[FaceObservation | None, float]:
    matches: list[tuple[FaceObservation, float]] = []
    for face in faces:
        match = best_character_match(face.embedding, references, character_id=character_id)
        if match is not None:
            matches.append((face, match[2]))
    if not matches:
        return None, 0.0
    return max(matches, key=lambda item: item[1])


def _smooth_keyframes(
    detections: list[tuple[float, float, float, float]],
) -> list[dict[str, float]]:
    if not detections:
        return []
    offsets = [item[1] for item in detections]
    median_filtered = []
    for index in range(len(offsets)):
        window = offsets[max(0, index - 1) : min(len(offsets), index + 2)]
        median_filtered.append(float(median(window)))
    smoothed: list[dict[str, float]] = []
    current = median_filtered[0]
    for (timestamp, _, lip_score, character_id), target in zip(
        detections, median_filtered, strict=True
    ):
        target = max(current - 0.22, min(current + 0.22, target))
        current = current * 0.45 + target * 0.55
        smoothed.append(
            {
                "time": round(timestamp, 3),
                "offset": round(current, 3),
                "lip_activity": round(lip_score, 3),
                "character_id": character_id,
            }
        )
    return smoothed


def _downscale720(frame, cv2_module):
    height, width = frame.shape[:2]
    if width > 720:
        scale = 720 / width
        return cv2_module.resize(frame, (720, max(1, round(height * scale))))
    return frame


def _prefetch_frames(capture, timestamps: list[float], cv2_module) -> dict[float, object]:
    """One sequential decode over the sampled window instead of ~2N keyframe seeks.

    `CAP_PROP_POS_MSEC` seeking re-decodes from the nearest keyframe every call,
    which is slow on long-GOP H.264. Here we seek once to the first wanted
    timestamp and read forward, `retrieve()`-ing only the frames we need.
    """
    wanted = sorted({round(t, 2) for t in timestamps})
    if not wanted:
        return {}
    fps = float(capture.get(cv2_module.CAP_PROP_FPS) or 0.0) or 25.0
    # Track position by frame index (increments reliably on grab() on every
    # backend, unlike CAP_PROP_POS_MSEC).
    capture.set(cv2_module.CAP_PROP_POS_FRAMES, max(0, int(wanted[0] * fps)))
    frame_no = int(capture.get(cv2_module.CAP_PROP_POS_FRAMES) or 0)  # where the seek actually landed
    start_frame = frame_no
    wanted_frames = [max(0, int(round(t * fps))) for t in wanted]
    out: dict[float, object] = {}
    index = 0
    guard = 0
    max_reads = (wanted_frames[-1] - start_frame) + len(wanted) + 64
    while index < len(wanted) and guard < max_reads:
        guard += 1
        if not capture.grab():
            break
        if frame_no < wanted_frames[index]:
            frame_no += 1
            continue
        ok, frame = capture.retrieve()
        scaled = _downscale720(frame, cv2_module) if ok and frame is not None else None
        while index < len(wanted) and frame_no >= wanted_frames[index]:
            if scaled is not None:
                out[wanted[index]] = scaled
            index += 1
        frame_no += 1
    return out
