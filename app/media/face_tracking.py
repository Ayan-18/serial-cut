from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class FaceTrackingResult:
    offset_x: float
    faces_detected: int
    frames_sampled: int


def estimate_face_offset(
    video_path: Path,
    start_time: float,
    end_time: float,
    samples: int = 9,
) -> FaceTrackingResult:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для анализа лиц")
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    centers: list[float] = []
    frames_sampled = 0
    duration = max(0.1, end_time - start_time)
    try:
        for index in range(samples):
            timestamp = start_time + duration * (index + 0.5) / samples
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            frames_sampled += 1
            height, width = frame.shape[:2]
            target_width = min(width, 720)
            if width > target_width:
                scale = target_width / width
                frame = cv2.resize(frame, (target_width, max(1, round(height * scale))))
                width = target_width
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(36, 36))
            if len(faces) == 0:
                continue
            x, _, face_width, _ = max(faces, key=lambda face: face[2] * face[3])
            center = (x + face_width / 2) / width
            centers.append(max(-1.0, min(1.0, (center - 0.5) * 2)))
    finally:
        capture.release()
    return FaceTrackingResult(
        offset_x=round(float(median(centers)) if centers else 0.0, 3),
        faces_detected=len(centers),
        frames_sampled=frames_sampled,
    )
