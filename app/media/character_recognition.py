from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CharacterProfile:
    character_id: int
    name: str
    photo_paths: list[Path]


@dataclass(frozen=True)
class RecognitionSuggestion:
    source_label: str
    character_id: int
    character_name: str
    confidence: float


def recognize_speaker_clusters(
    video_path: Path,
    labeled_ranges: dict[str, list[tuple[float, float]]],
    profiles: list[CharacterProfile],
    samples_per_label: int = 10,
) -> list[RecognitionSuggestion]:
    import cv2

    reference_vectors = _reference_vectors(profiles)
    if not reference_vectors:
        return []
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для распознавания персонажей")
    cascade = _face_cascade(cv2)
    suggestions: list[RecognitionSuggestion] = []
    try:
        for source_label, ranges in sorted(labeled_ranges.items()):
            selected = _evenly_spaced(ranges, samples_per_label)
            matches: list[tuple[int, str, float]] = []
            for start, end in selected:
                capture.set(cv2.CAP_PROP_POS_MSEC, ((start + end) / 2) * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue
                face = _largest_face(frame, cascade, cv2)
                if face is None:
                    continue
                match = _best_match(face_signature(face, cv2), reference_vectors)
                if match is not None:
                    matches.append(match)
            suggestion = _majority_suggestion(source_label, matches)
            if suggestion is not None:
                suggestions.append(suggestion)
    finally:
        capture.release()
    return suggestions


def face_signature(image: np.ndarray, cv2_module=None) -> np.ndarray:
    if cv2_module is None:
        import cv2 as cv2_module

    gray = image if image.ndim == 2 else cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY)
    normalized = cv2_module.resize(gray, (96, 96), interpolation=cv2_module.INTER_AREA)
    normalized = cv2_module.equalizeHist(normalized)
    dct = cv2_module.dct(normalized.astype(np.float32) / 255.0)
    vector = dct[:20, :20].reshape(-1)[1:]
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else vector


def _reference_vectors(profiles: list[CharacterProfile]) -> list[tuple[int, str, np.ndarray]]:
    import cv2

    cascade = _face_cascade(cv2)
    vectors: list[tuple[int, str, np.ndarray]] = []
    for profile in profiles:
        for path in profile.photo_paths:
            image = cv2.imread(str(path))
            if image is None:
                continue
            face = _largest_face(image, cascade, cv2)
            if face is None:
                face = image
            vectors.append((profile.character_id, profile.name, face_signature(face, cv2)))
    return vectors


def _face_cascade(cv2_module):
    cascade_path = Path(cv2_module.data.haarcascades) / "haarcascade_frontalface_default.xml"
    return cv2_module.CascadeClassifier(str(cascade_path))


def _largest_face(frame: np.ndarray, cascade, cv2_module) -> np.ndarray | None:
    gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    faces = cascade.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(48, 48))
    if len(faces) == 0:
        return None
    x, y, width, height = max(faces, key=lambda item: item[2] * item[3])
    pad_x = round(width * 0.12)
    pad_y = round(height * 0.12)
    left = max(0, x - pad_x)
    top = max(0, y - pad_y)
    right = min(frame.shape[1], x + width + pad_x)
    bottom = min(frame.shape[0], y + height + pad_y)
    return frame[top:bottom, left:right]


def _best_match(
    vector: np.ndarray,
    references: list[tuple[int, str, np.ndarray]],
    threshold: float = 0.86,
    margin: float = 0.04,
) -> tuple[int, str, float] | None:
    best_by_character: dict[int, tuple[int, str, float]] = {}
    for character_id, name, reference in references:
        score = float(np.dot(vector, reference))
        current = best_by_character.get(character_id)
        if current is None or score > current[2]:
            best_by_character[character_id] = (character_id, name, score)
    scores = sorted(best_by_character.values(), key=lambda item: item[2], reverse=True)
    if not scores or scores[0][2] < threshold:
        return None
    if len(scores) > 1 and scores[0][2] - scores[1][2] < margin:
        return None
    return scores[0]


def _majority_suggestion(
    source_label: str,
    matches: list[tuple[int, str, float]],
) -> RecognitionSuggestion | None:
    if len(matches) < 2:
        return None
    counts: dict[int, int] = {}
    for character_id, _, _ in matches:
        counts[character_id] = counts.get(character_id, 0) + 1
    winner_id, winner_count = max(counts.items(), key=lambda item: item[1])
    if winner_count / len(matches) < 0.65:
        return None
    winner_matches = [item for item in matches if item[0] == winner_id]
    return RecognitionSuggestion(
        source_label=source_label,
        character_id=winner_id,
        character_name=winner_matches[0][1],
        confidence=round(sum(item[2] for item in winner_matches) / len(winner_matches), 3),
    )


def _evenly_spaced(items: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    if len(items) <= limit:
        return items
    positions = np.linspace(0, len(items) - 1, limit).round().astype(int)
    return [items[int(index)] for index in positions]
