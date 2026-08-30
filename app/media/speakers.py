from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import TranscriptSegment


def assign_speaker_labels(session: Session, episode_id: int, audio_path: Path) -> int:
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.episode_id == episode_id)
        .order_by(TranscriptSegment.start_time)
    ).all()
    if not segments:
        return 0
    sample_rate, audio = _read_mono_pcm(audio_path)
    features = np.asarray([_voice_features(audio, sample_rate, item.start_time, item.end_time) for item in segments])
    cluster_count = 1 if len(segments) < 4 else min(3, max(2, len(segments) // 35 + 1))
    labels = _kmeans(features, cluster_count)
    for segment, label in zip(segments, labels, strict=True):
        segment.speaker_label = f"Говорящий {int(label) + 1}"
    session.flush()
    return cluster_count


def _read_mono_pcm(path: Path) -> tuple[int, np.ndarray]:
    try:
        with wave.open(str(path), "rb") as handle:
            sample_rate = handle.getframerate()
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            raw = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise RuntimeError("Не удалось прочитать WAV для определения говорящих") from exc
    if sample_width != 2:
        raise RuntimeError("Для определения говорящих требуется PCM WAV 16-bit")
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return sample_rate, audio


def _voice_features(audio: np.ndarray, sample_rate: int, start: float, end: float) -> np.ndarray:
    left = max(0, int(start * sample_rate))
    right = min(len(audio), max(left + 1, int(end * sample_rate)))
    chunk = audio[left:right]
    if len(chunk) > sample_rate * 4:
        chunk = chunk[: sample_rate * 4]
    if len(chunk) < 64:
        return np.zeros(6, dtype=np.float32)
    chunk = chunk - float(chunk.mean())
    energy = float(np.sqrt(np.mean(chunk * chunk)) + 1e-8)
    zcr = float(np.mean(np.abs(np.diff(np.signbit(chunk)))))
    window = np.hanning(len(chunk))
    spectrum = np.abs(np.fft.rfft(chunk * window)) + 1e-8
    frequencies = np.fft.rfftfreq(len(chunk), d=1.0 / sample_rate)
    spectrum_sum = float(spectrum.sum())
    centroid = float((spectrum * frequencies).sum() / spectrum_sum / (sample_rate / 2))
    bands = []
    for low, high in ((80, 500), (500, 1500), (1500, 4000)):
        mask = (frequencies >= low) & (frequencies < high)
        bands.append(float(spectrum[mask].sum() / spectrum_sum))
    return np.asarray([np.log(energy), zcr, centroid, *bands], dtype=np.float32)


def _kmeans(features: np.ndarray, count: int) -> np.ndarray:
    if count <= 1 or len(features) <= 1:
        return np.zeros(len(features), dtype=np.int32)
    means = features.mean(axis=0)
    scales = features.std(axis=0)
    normalized = (features - means) / np.where(scales < 1e-6, 1.0, scales)
    order = np.argsort(normalized[:, 2])
    positions = np.linspace(0, len(order) - 1, count).round().astype(int)
    centers = normalized[order[positions]].copy()
    labels = np.full(len(features), -1, dtype=np.int32)
    for _ in range(20):
        distances = ((normalized[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        next_labels = distances.argmin(axis=1).astype(np.int32)
        if np.array_equal(labels, next_labels):
            break
        labels = next_labels
        for index in range(count):
            members = normalized[labels == index]
            if len(members):
                centers[index] = members.mean(axis=0)
    center_order = np.argsort(centers[:, 2])
    remap = {int(old): new for new, old in enumerate(center_order)}
    return np.asarray([remap[int(label)] for label in labels], dtype=np.int32)
