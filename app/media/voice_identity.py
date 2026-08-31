from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.media.speakers import _read_mono_pcm


VOICE_PROFILE_VERSION = 1


@dataclass(frozen=True)
class VoiceEmbedding:
    vector: np.ndarray
    sample_count: int
    seconds: float


@dataclass(frozen=True)
class VoiceProfile:
    character_id: int
    character_name: str
    vector: np.ndarray
    sample_count: int


@dataclass(frozen=True)
class VoiceSuggestion:
    source_label: str
    character_id: int
    character_name: str
    confidence: float


def extract_voice_embedding(
    audio_path: Path,
    ranges: list[tuple[float, float]],
    max_samples: int = 16,
) -> VoiceEmbedding | None:
    sample_rate, audio = _read_mono_pcm(audio_path)
    selected = _evenly_spaced(ranges, max_samples)
    vectors: list[np.ndarray] = []
    total_seconds = 0.0
    for start, end in selected:
        left = max(0, int(start * sample_rate))
        right = min(len(audio), int(min(end, start + 5.0) * sample_rate))
        if right - left < sample_rate * 0.45:
            continue
        chunk = audio[left:right]
        if float(np.sqrt(np.mean(chunk * chunk))) < 0.006:
            continue
        vectors.append(voice_signature(chunk, sample_rate))
        total_seconds += (right - left) / sample_rate
    if not vectors:
        return None
    vector = _normalized(np.mean(np.stack(vectors), axis=0))
    return VoiceEmbedding(vector, len(vectors), round(total_seconds, 3))


def voice_signature(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Build a local text-independent spectral voiceprint.

    The profile intentionally avoids sending audio anywhere. Log-mel cepstra and their temporal
    changes make it substantially more stable than the six-value Stage 2 clustering heuristic.
    """

    signal = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not len(signal):
        return np.zeros(76, dtype=np.float32)
    signal = signal - float(signal.mean())
    peak = float(np.max(np.abs(signal)))
    if peak > 1e-6:
        signal = signal / peak
    signal = np.append(signal[0], signal[1:] - 0.97 * signal[:-1])
    frame_length = max(160, round(sample_rate * 0.025))
    frame_step = max(80, round(sample_rate * 0.010))
    if len(signal) < frame_length:
        signal = np.pad(signal, (0, frame_length - len(signal)))
    frame_count = 1 + (len(signal) - frame_length) // frame_step
    indices = np.arange(frame_length)[None, :] + frame_step * np.arange(frame_count)[:, None]
    frames = signal[indices] * np.hamming(frame_length)[None, :]
    fft_size = 1 << int(np.ceil(np.log2(frame_length)))
    power = np.abs(np.fft.rfft(frames, n=fft_size, axis=1)) ** 2
    mel_bank = _mel_filter_bank(sample_rate, fft_size, 32)
    log_mel = np.log(np.maximum(power @ mel_bank.T, 1e-9))
    dct = _dct_basis(32, 20)
    cepstra = log_mel @ dct.T
    delta = np.gradient(cepstra, axis=0) if len(cepstra) > 1 else np.zeros_like(cepstra)
    statistics = np.concatenate(
        [
            _normalized(cepstra.mean(axis=0)[1:]),
            _normalized(cepstra.std(axis=0)[1:]),
            _normalized(delta.mean(axis=0)[1:]),
            _normalized(delta.std(axis=0)[1:]),
        ]
    )
    return _normalized(statistics.astype(np.float32))


def merge_voice_profile(existing: dict | None, embedding: VoiceEmbedding) -> dict:
    previous_vector = None
    previous_count = 0
    previous_seconds = 0.0
    if existing and existing.get("version") == VOICE_PROFILE_VERSION:
        try:
            candidate = np.asarray(existing["vector"], dtype=np.float32)
            if candidate.shape == embedding.vector.shape:
                previous_vector = candidate
                previous_count = max(0, int(existing.get("sample_count", 0)))
                previous_seconds = max(0.0, float(existing.get("seconds", 0)))
        except (KeyError, TypeError, ValueError):
            previous_vector = None
    if previous_vector is None or previous_count == 0:
        merged = embedding.vector
        total_count = embedding.sample_count
    else:
        merged = _normalized(
            previous_vector * previous_count + embedding.vector * embedding.sample_count
        )
        total_count = previous_count + embedding.sample_count
    return {
        "version": VOICE_PROFILE_VERSION,
        "vector": [round(float(item), 7) for item in merged],
        "sample_count": total_count,
        "seconds": round(previous_seconds + embedding.seconds, 3),
    }


def voice_profile_from_json(character_id: int, name: str, payload: dict | None) -> VoiceProfile | None:
    if not payload or payload.get("version") != VOICE_PROFILE_VERSION:
        return None
    try:
        vector = _normalized(np.asarray(payload["vector"], dtype=np.float32))
        sample_count = int(payload.get("sample_count", 0))
    except (KeyError, TypeError, ValueError):
        return None
    if vector.shape != (76,) or sample_count <= 0:
        return None
    return VoiceProfile(character_id, name, vector, sample_count)


def recognize_voice_clusters(
    audio_path: Path,
    labeled_ranges: dict[str, list[tuple[float, float]]],
    profiles: list[VoiceProfile],
    threshold: float = 0.82,
    margin: float = 0.035,
) -> tuple[list[VoiceSuggestion], dict[str, VoiceEmbedding]]:
    embeddings: dict[str, VoiceEmbedding] = {}
    suggestions: list[VoiceSuggestion] = []
    for source_label, ranges in sorted(labeled_ranges.items()):
        embedding = extract_voice_embedding(audio_path, ranges)
        if embedding is None:
            continue
        embeddings[source_label] = embedding
        scores = sorted(
            (
                (profile, float(np.dot(embedding.vector, profile.vector)))
                for profile in profiles
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if not scores or scores[0][1] < threshold:
            continue
        if len(scores) > 1 and scores[0][1] - scores[1][1] < margin:
            continue
        profile, confidence = scores[0]
        suggestions.append(
            VoiceSuggestion(
                source_label=source_label,
                character_id=profile.character_id,
                character_name=profile.character_name,
                confidence=round(confidence, 3),
            )
        )
    return suggestions, embeddings


def _mel_filter_bank(sample_rate: int, fft_size: int, filters: int) -> np.ndarray:
    def hz_to_mel(value: float) -> float:
        return 2595.0 * np.log10(1.0 + value / 700.0)

    def mel_to_hz(value: np.ndarray) -> np.ndarray:
        return 700.0 * (10 ** (value / 2595.0) - 1.0)

    mel_points = np.linspace(hz_to_mel(70), hz_to_mel(sample_rate / 2), filters + 2)
    bins = np.floor((fft_size + 1) * mel_to_hz(mel_points) / sample_rate).astype(int)
    bank = np.zeros((filters, fft_size // 2 + 1), dtype=np.float32)
    for index in range(filters):
        left, center, right = bins[index : index + 3]
        center = max(left + 1, center)
        right = max(center + 1, right)
        for position in range(left, min(center, bank.shape[1])):
            bank[index, position] = (position - left) / (center - left)
        for position in range(center, min(right, bank.shape[1])):
            bank[index, position] = (right - position) / (right - center)
    return bank


def _dct_basis(input_size: int, output_size: int) -> np.ndarray:
    positions = np.arange(input_size, dtype=np.float32) + 0.5
    components = np.arange(output_size, dtype=np.float32)[:, None]
    return np.cos(np.pi / input_size * components * positions[None, :]).astype(np.float32)


def _normalized(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else vector


def _evenly_spaced(items: list[tuple[float, float]], limit: int) -> list[tuple[float, float]]:
    if len(items) <= limit:
        return items
    positions = np.linspace(0, len(items) - 1, limit).round().astype(int)
    return [items[int(index)] for index in positions]
