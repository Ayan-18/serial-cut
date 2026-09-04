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
    lip_confidence: float
    face_model: str


@dataclass(frozen=True)
class FaceObservation:
    x: int
    y: int
    width: int
    height: int
    score: float
    embedding: np.ndarray
    landmarks: tuple[tuple[float, float], ...] = ()

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


class LocalFaceRecognizer:
    """YuNet + SFace face identification, active only when the local ONNX weights exist.

    OpenCV 5 headless ships no Haar cascade, so without the neural weights there is
    no face detection at all and the pipeline falls back to voice-only identity.
    """

    def __init__(self, detector_model: Path | None = None, recognizer_model: Path | None = None):
        import cv2

        self.cv2 = cv2
        self.detector = None
        self.recognizer = None
        if detector_model and recognizer_model and detector_model.exists() and recognizer_model.exists():
            try:
                self.detector = cv2.FaceDetectorYN.create(
                    str(detector_model), "", (320, 320), 0.72, 0.3, 5000
                )
                self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model), "")
            except cv2.error:
                self.detector = None
                self.recognizer = None

    @property
    def neural(self) -> bool:
        return self.detector is not None and self.recognizer is not None

    @property
    def can_detect(self) -> bool:
        """Whether this build can find faces at all (i.e. the neural weights loaded)."""
        return self.neural

    @property
    def model_name(self) -> str:
        if self.neural:
            return "YuNet + SFace"
        return "Только голос (лица не распознаются без YuNet/SFace)"

    def detect(self, frame: np.ndarray) -> list[FaceObservation]:
        if frame is None or frame.size == 0 or not self.neural:
            return []
        return self._detect_neural(frame)

    def _detect_neural(self, frame: np.ndarray) -> list[FaceObservation]:
        assert self.detector is not None and self.recognizer is not None
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return []
        observations: list[FaceObservation] = []
        for face in faces:
            row = np.asarray(face, dtype=np.float32)
            try:
                aligned = self.recognizer.alignCrop(frame, row)
                vector = np.asarray(self.recognizer.feature(aligned), dtype=np.float32).reshape(-1)
            except self.cv2.error:
                continue
            x, y, face_width, face_height = [int(round(value)) for value in row[:4]]
            x = max(0, min(width - 1, x))
            y = max(0, min(height - 1, y))
            face_width = max(1, min(width - x, face_width))
            face_height = max(1, min(height - y, face_height))
            landmarks = tuple((float(row[index]), float(row[index + 1])) for index in range(4, 14, 2))
            observations.append(
                FaceObservation(
                    x=x,
                    y=y,
                    width=face_width,
                    height=face_height,
                    score=float(row[14]),
                    embedding=_normalized(vector),
                    landmarks=landmarks,
                )
            )
        return observations

def recognize_speaker_clusters(
    video_path: Path,
    labeled_ranges: dict[str, list[tuple[float, float]]],
    profiles: list[CharacterProfile],
    detector_model: Path | None = None,
    recognizer_model: Path | None = None,
    samples_per_label: int = 12,
) -> tuple[list[RecognitionSuggestion], str]:
    import cv2

    engine = LocalFaceRecognizer(detector_model, recognizer_model)
    reference_vectors = build_reference_vectors(engine, profiles)
    if not reference_vectors:
        return [], engine.model_name
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("Не удалось открыть видео для распознавания персонажей")
    suggestions: list[RecognitionSuggestion] = []
    try:
        for source_label, ranges in sorted(labeled_ranges.items()):
            selected = _evenly_spaced(ranges, samples_per_label)
            matches: list[tuple[int, str, float, float]] = []
            for start, end in selected:
                timestamp = (start + end) / 2
                current = _read_frame(capture, timestamp, cv2)
                previous = _read_frame(capture, max(start, timestamp - 0.12), cv2)
                if current is None or previous is None:
                    continue
                current_faces = engine.detect(current)
                previous_faces = engine.detect(previous)
                selected_face, lip_score = select_lip_active_face(
                    current, current_faces, previous, previous_faces, cv2
                )
                if selected_face is None or lip_score < 0.012:
                    continue
                match = best_character_match(selected_face.embedding, reference_vectors)
                if match is not None:
                    matches.append((*match, lip_score))
            suggestion = _majority_suggestion(source_label, matches, engine.model_name)
            if suggestion is not None:
                suggestions.append(suggestion)
    finally:
        capture.release()
    return suggestions, engine.model_name


def build_reference_vectors(
    engine: LocalFaceRecognizer,
    profiles: list[CharacterProfile],
) -> list[tuple[int, str, np.ndarray]]:
    cv2 = engine.cv2
    vectors: list[tuple[int, str, np.ndarray]] = []
    for profile in profiles:
        for path in profile.photo_paths:
            image = cv2.imread(str(path))
            if image is None:
                continue
            image = _downscale(image, 1280, cv2)
            faces = engine.detect(image)
            if not faces:
                continue
            face = max(faces, key=lambda item: item.width * item.height)
            vectors.append((profile.character_id, profile.name, face.embedding))
    return vectors


def best_character_match(
    vector: np.ndarray,
    references: list[tuple[int, str, np.ndarray]],
    character_id: int | None = None,
) -> tuple[int, str, float] | None:
    best_by_character: dict[int, tuple[int, str, float]] = {}
    for reference_character_id, name, reference in references:
        if character_id is not None and reference_character_id != character_id:
            continue
        score = float(np.dot(vector, reference))
        current = best_by_character.get(reference_character_id)
        if current is None or score > current[2]:
            best_by_character[reference_character_id] = (reference_character_id, name, score)
    scores = sorted(best_by_character.values(), key=lambda item: item[2], reverse=True)
    threshold = 0.43  # SFace cosine similarity
    margin = 0.07
    if not scores or scores[0][2] < threshold:
        return None
    if character_id is None and len(scores) > 1 and scores[0][2] - scores[1][2] < margin:
        return None
    return scores[0]


def select_lip_active_face(
    current_frame: np.ndarray,
    current_faces: list[FaceObservation],
    previous_frame: np.ndarray,
    previous_faces: list[FaceObservation],
    cv2_module=None,
) -> tuple[FaceObservation | None, float]:
    if cv2_module is None:
        import cv2 as cv2_module
    if not current_faces or not previous_faces:
        return None, 0.0
    scored: list[tuple[FaceObservation, float]] = []
    diagonal = max(1.0, float(np.hypot(current_frame.shape[1], current_frame.shape[0])))
    for face in current_faces:
        previous = min(
            previous_faces,
            key=lambda item: np.hypot(face.center_x - item.center_x, face.center_y - item.center_y),
        )
        distance = float(np.hypot(face.center_x - previous.center_x, face.center_y - previous.center_y))
        if distance / diagonal > 0.18:
            continue
        score = mouth_motion_score(current_frame, face, previous_frame, previous, cv2_module)
        scored.append((face, score))
    if not scored:
        return None, 0.0
    return max(scored, key=lambda item: item[1])


def mouth_motion_score(
    current_frame: np.ndarray,
    current_face: FaceObservation,
    previous_frame: np.ndarray,
    previous_face: FaceObservation,
    cv2_module=None,
) -> float:
    if cv2_module is None:
        import cv2 as cv2_module
    current = _mouth_crop(current_frame, current_face, cv2_module)
    previous = _mouth_crop(previous_frame, previous_face, cv2_module)
    if current is None or previous is None:
        return 0.0
    current = cv2_module.resize(current, (48, 24), interpolation=cv2_module.INTER_AREA)
    previous = cv2_module.resize(previous, (48, 24), interpolation=cv2_module.INTER_AREA)
    current = current.astype(np.float32)
    previous = previous.astype(np.float32)
    current = (current - current.mean()) / max(8.0, float(current.std()))
    previous = (previous - previous.mean()) / max(8.0, float(previous.std()))
    return float(np.mean(np.abs(current - previous)))




def _mouth_crop(frame: np.ndarray, face: FaceObservation, cv2_module) -> np.ndarray | None:
    gray = frame if frame.ndim == 2 else cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
    if len(face.landmarks) >= 5:
        mouth_left, mouth_right = face.landmarks[3], face.landmarks[4]
        center_x = (mouth_left[0] + mouth_right[0]) / 2
        center_y = (mouth_left[1] + mouth_right[1]) / 2
        mouth_width = max(abs(mouth_right[0] - mouth_left[0]) * 2.1, face.width * 0.34)
        mouth_height = max(face.height * 0.28, mouth_width * 0.42)
        left = int(center_x - mouth_width / 2)
        right = int(center_x + mouth_width / 2)
        top = int(center_y - mouth_height * 0.35)
        bottom = int(center_y + mouth_height * 0.65)
    else:
        left = int(face.x + face.width * 0.18)
        right = int(face.x + face.width * 0.82)
        top = int(face.y + face.height * 0.58)
        bottom = int(face.y + face.height * 0.93)
    left, right = max(0, left), min(gray.shape[1], right)
    top, bottom = max(0, top), min(gray.shape[0], bottom)
    if right - left < 8 or bottom - top < 5:
        return None
    return gray[top:bottom, left:right]


def _majority_suggestion(
    source_label: str,
    matches: list[tuple[int, str, float, float]],
    face_model: str,
) -> RecognitionSuggestion | None:
    if len(matches) < 2:
        return None
    counts: dict[int, int] = {}
    for character_id, _, _, _ in matches:
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
        lip_confidence=round(sum(item[3] for item in winner_matches) / len(winner_matches), 3),
        face_model=face_model,
    )


def _read_frame(capture, timestamp: float, cv2_module) -> np.ndarray | None:
    capture.set(cv2_module.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000)
    ok, frame = capture.read()
    if not ok:
        return None
    return _downscale(frame, 720, cv2_module)


def _downscale(frame: np.ndarray, max_width: int, cv2_module) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    return cv2_module.resize(frame, (max_width, max(1, round(height * scale))))


def _normalized(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else vector


def _evenly_spaced(items: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    if len(items) <= limit:
        return items
    positions = np.linspace(0, len(items) - 1, limit).round().astype(int)
    return [items[int(index)] for index in positions]
