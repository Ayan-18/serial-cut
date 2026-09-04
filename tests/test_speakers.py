from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from app.media.speakers import _kmeans, _read_mono_pcm, _voice_features, assign_speaker_labels
from app.models.entities import Episode, Season, TranscriptSegment


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000, width: int = 2) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(width)
        handle.setframerate(sample_rate)
        if width == 2:
            handle.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        else:
            handle.writeframes(((np.clip(samples, -1, 1) + 1) * 127).astype(np.uint8).tobytes())


def _tone(freq: float, seconds: float, sample_rate: int = 16000) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    return 0.5 * np.sin(2 * np.pi * freq * t)


def test_kmeans_separates_two_obvious_clusters():
    features = np.array([[0.0, 0.0, 0.0]] * 5 + [[10.0, 10.0, 10.0]] * 5, dtype=np.float32)

    labels = _kmeans(features, 2)

    assert len(set(labels[:5])) == 1
    assert len(set(labels[5:])) == 1
    assert labels[0] != labels[5]


def test_kmeans_is_a_noop_for_a_single_cluster():
    assert list(_kmeans(np.zeros((4, 3), dtype=np.float32), 1)) == [0, 0, 0, 0]


def test_read_mono_pcm_roundtrips_16bit(tmp_path: Path):
    path = tmp_path / "a.wav"
    _write_wav(path, _tone(200, 0.5))

    rate, audio = _read_mono_pcm(path)

    assert rate == 16000
    assert audio.dtype == np.float32
    assert 0.3 < float(np.abs(audio).max()) <= 1.0


def test_read_mono_pcm_rejects_non_16bit(tmp_path: Path):
    path = tmp_path / "b.wav"
    _write_wav(path, _tone(200, 0.2), width=1)

    with pytest.raises(RuntimeError, match="16-bit"):
        _read_mono_pcm(path)


def test_voice_features_is_six_dim_and_deterministic():
    audio = _tone(300, 1.0)

    first = _voice_features(audio, 16000, 0.0, 1.0)
    second = _voice_features(audio, 16000, 0.0, 1.0)

    assert first.shape == (6,)
    assert np.allclose(first, second)


def test_assign_speaker_labels_splits_two_distinct_voices(session, tmp_path: Path):
    season = Season(title="S", root_path="C:/spk")
    session.add(season)
    session.flush()
    episode = Episode(
        season_id=season.id, file_path="C:/spk/e.mkv", file_name="e.mkv",
        fingerprint="fp-spk", size_bytes=1, modified_ns=1,
    )
    session.add(episode)
    session.flush()

    # 0–4 s low voice, 4–8 s bright voice, alternating across 8 segments.
    audio = np.concatenate([_tone(140, 4.0), _tone(1900, 4.0)])
    _write_wav(tmp_path / "voice.wav", audio)
    for index in range(8):
        start = index * 1.0
        session.add(
            TranscriptSegment(
                episode_id=episode.id, start_time=start, end_time=start + 0.9,
                text=f"с{index}", speaker_label=None,
            )
        )
    session.flush()

    clusters = assign_speaker_labels(session, episode.id, tmp_path / "voice.wav")

    rows = sorted(session.query(TranscriptSegment).all(), key=lambda s: s.start_time)
    labels = [s.speaker_label for s in rows]
    assert clusters == 2
    assert set(labels) == {"Говорящий 1", "Говорящий 2"}
    assert labels[0] != labels[-1]  # first (low) and last (bright) landed in different clusters
